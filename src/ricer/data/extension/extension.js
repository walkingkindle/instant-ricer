// Ricer's part inside GNOME Shell: what the top bar shows where the clock is, and the cards
// in the menu that opens from it. Everything is decided by ricer and read from one file;
// this only draws it, and puts the stock clock back when it is switched off.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Config from 'resource:///org/gnome/shell/misc/config.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const CONFIG = GLib.build_filenamev([GLib.get_user_config_dir(), 'ricer', 'shell.json']);
const REFRESH_SECONDS = 2;           // how often the cards update, and only while the menu is open
const RELOAD_DELAY_MS = 150;         // a rewrite of the file arrives as several events
const COLOUR = /^#[0-9a-fA-F]{6}$/;
const CENTER = Clutter.ActorAlign.CENTER;

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytes) : null;
    } catch {
        return null;
    }
}

function readConfig() {
    try {
        const config = JSON.parse(readText(CONFIG) ?? '{}');
        return config && typeof config === 'object' ? config : {};
    } catch {
        return {};
    }
}

function percent(fraction) {
    return `${Math.round(fraction * 100)}%`;
}

function card(config, title) {
    const box = new St.BoxLayout({vertical: true, style_class: 'ricer-card'});
    if (title) {
        box.add_child(new St.Label({
            text: config.caps ? title.toUpperCase() : title,
            style_class: config.caps ? 'ricer-title ricer-caps' : 'ricer-title',
        }));
    }
    return box;
}

// A bar as wide as it is given, with its one child filling a fraction of it from the start.
const Track = GObject.registerClass(
class RicerTrack extends St.Widget {
    _init() {
        super._init({style_class: 'ricer-track', x_expand: true, y_align: CENTER});
        this._fraction = 0;
        this.add_child(new St.Widget({style_class: 'ricer-fill'}));
    }

    setFraction(fraction) {
        this._fraction = Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0));
        this.queue_relayout();
    }

    vfunc_allocate(box) {
        this.set_allocation(box);
        const inside = this.get_theme_node().get_content_box(box);
        const width = Math.round((inside.x2 - inside.x1) * this._fraction);
        const filled = new Clutter.ActorBox();
        const fromRight = this.get_text_direction() === Clutter.TextDirection.RTL;
        filled.x1 = fromRight ? inside.x2 - width : inside.x1;
        filled.x2 = filled.x1 + width;
        filled.y1 = inside.y1;
        filled.y2 = inside.y2;
        this.get_first_child().allocate(filled);
    }
});

// One line of a card: a name, a bar filled to a fraction, and the value in words.
class Meter {
    constructor(name) {
        this.actor = new St.BoxLayout({style_class: 'ricer-row'});
        this._track = new Track();
        this._value = new St.Label({style_class: 'ricer-value', y_align: CENTER});
        this.actor.add_child(new St.Label({text: name, style_class: 'ricer-key', y_align: CENTER}));
        this.actor.add_child(this._track);
        this.actor.add_child(this._value);
    }

    set(fraction, text) {
        this._track.setFraction(fraction);
        this._value.text = text;
    }
}

// -- readings ------------------------------------------------------------------------------

function cpuTimes() {
    const line = (readText('/proc/stat') ?? '').split('\n')[0];
    const fields = line.trim().split(/\s+/).slice(1).map(Number);
    if (fields.length < 4 || fields.some(Number.isNaN))
        return null;
    const idle = fields[3] + (fields[4] ?? 0);
    return {idle, total: fields.reduce((sum, value) => sum + value, 0)};
}

function memory() {
    const kb = {};
    for (const line of (readText('/proc/meminfo') ?? '').split('\n')) {
        const match = /^(MemTotal|MemAvailable):\s+(\d+)/.exec(line);
        if (match)
            kb[match[1]] = Number(match[2]);
    }
    return kb.MemTotal ? {total: kb.MemTotal, used: kb.MemTotal - (kb.MemAvailable ?? 0)} : null;
}

function disk() {
    try {
        const info = Gio.File.new_for_path(GLib.get_home_dir()).query_filesystem_info(
            'filesystem::size,filesystem::free', null);
        const size = info.get_attribute_uint64('filesystem::size');
        return size ? 1 - info.get_attribute_uint64('filesystem::free') / size : null;
    } catch {
        return null;
    }
}

// The file holding the processor's temperature, or null on a machine that reports none.
function temperatureFile() {
    for (let index = 0; index < 16; index++) {
        const folder = `/sys/class/hwmon/hwmon${index}`;
        const name = (readText(`${folder}/name`) ?? '').trim();
        if (['coretemp', 'k10temp', 'zenpower', 'cpu_thermal'].includes(name) &&
            readText(`${folder}/temp1_input`) !== null)
            return `${folder}/temp1_input`;
    }
    const zone = '/sys/class/thermal/thermal_zone0/temp';
    return readText(zone) !== null ? zone : null;
}

function uptime() {
    const seconds = parseFloat(readText('/proc/uptime') ?? '');
    if (!Number.isFinite(seconds))
        return '';
    const minutes = Math.floor(seconds / 60);
    const days = Math.floor(minutes / 1440), hours = Math.floor(minutes / 60) % 24;
    if (days)
        return `up ${days}d ${hours}h`;
    return hours ? `up ${hours}h ${minutes % 60}m` : `up ${minutes}m`;
}

function processor() {
    const match = /^model name\s*:\s*(.+)$/m.exec(readText('/proc/cpuinfo') ?? '');
    return match ? match[1].replace(/\((R|TM)\)/gi, '').replace(/\s+CPU\b/, '')
        .replace(/\s+@.*$/, '').replace(/\s+\d+-Core Processor$/, '').replace(/\s+/g, ' ').trim() : '';
}

// -- the cards: each returns its actor, and a function that brings it up to date ------------

function profileCard(config) {
    const box = card(config, null);
    const row = new St.BoxLayout({style_class: 'ricer-profile'});
    const avatar = new St.Bin({style_class: 'ricer-avatar', y_align: CENTER});
    const user = GLib.get_user_name();
    const picture = [`/var/lib/AccountsService/icons/${user}`, `${GLib.get_home_dir()}/.face`]
        .find(path => !/["'()\\\n]/.test(path) && GLib.file_test(path, GLib.FileTest.IS_REGULAR));
    if (picture)
        avatar.style = `background-image: url("${picture}");`;
    else
        avatar.child = new St.Icon({icon_name: 'avatar-default-symbolic'});

    const words = new St.BoxLayout({vertical: true, y_align: CENTER, x_expand: true});
    const real = GLib.get_real_name();
    words.add_child(new St.Label({
        text: real && real !== 'Unknown' ? real : user, style_class: 'ricer-name',
    }));
    words.add_child(new St.Label({text: `${user}@${GLib.get_host_name()}`, style_class: 'ricer-dim'}));
    const up = new St.Label({style_class: 'ricer-dim'});
    words.add_child(up);
    row.add_child(avatar);
    row.add_child(words);
    box.add_child(row);
    return {actor: box, update: () => (up.text = uptime())};
}

function systemCard(config, state) {
    const box = card(config, 'System');
    const cpu = new Meter('CPU'), ram = new Meter('Memory'), drive = new Meter('Disk');
    const heat = state.temperature ? new Meter('Temp') : null;
    for (const meter of [cpu, ram, heat, drive]) {
        if (meter)
            box.add_child(meter.actor);
    }
    const update = () => {
        const now = cpuTimes(), before = state.cpu;
        if (now && before && now.total > before.total) {
            const busy = 1 - (now.idle - before.idle) / (now.total - before.total);
            cpu.set(busy, percent(busy));
        }
        state.cpu = now ?? before;
        const mem = memory();
        if (mem)
            ram.set(mem.used / mem.total, `${(mem.used / 1048576).toFixed(1)}G`);
        const full = disk();
        if (full !== null)
            drive.set(full, percent(full));
        const degrees = heat ? parseInt(readText(state.temperature) ?? '') / 1000 : NaN;
        if (Number.isFinite(degrees))
            heat.set(degrees / 100, `${Math.round(degrees)}°`);
    };
    return {actor: box, update};
}

function progressCard(config) {
    const box = card(config, 'Time gone');
    const meters = {
        day: new Meter('Day'), week: new Meter('Week'), month: new Meter('Month'),
        year: new Meter('Year'),
    };
    for (const meter of Object.values(meters))
        box.add_child(meter.actor);
    const update = () => {
        const now = new Date();
        const between = (start, end) => (now - start) / (end - start);
        const year = now.getFullYear(), month = now.getMonth(), date = now.getDate();
        const monday = date - (now.getDay() + 6) % 7;
        const parts = {
            day: between(new Date(year, month, date), new Date(year, month, date + 1)),
            week: between(new Date(year, month, monday), new Date(year, month, monday + 7)),
            month: between(new Date(year, month, 1), new Date(year, month + 1, 1)),
            year: between(new Date(year, 0, 1), new Date(year + 1, 0, 1)),
        };
        for (const [name, part] of Object.entries(parts))
            meters[name].set(part, percent(part));
    };
    return {actor: box, update};
}

function fetchCard(config) {
    const box = card(config, 'This machine');
    const mem = memory();
    const rows = [
        ['OS', GLib.get_os_info('PRETTY_NAME') ?? GLib.get_os_info('NAME') ?? ''],
        ['Kernel', (readText('/proc/sys/kernel/osrelease') ?? '').trim()],
        ['Shell', `GNOME ${Config.PACKAGE_VERSION}`],
        ['CPU', processor()],
        ['Memory', mem ? `${Math.round(mem.total / 1048576)} GB` : ''],
    ];
    for (const [key, value] of rows) {
        if (!value)
            continue;
        const row = new St.BoxLayout({style_class: 'ricer-row'});
        row.add_child(new St.Label({text: key, style_class: 'ricer-key ricer-fetch-key'}));
        row.add_child(new St.Label({text: value, x_expand: true}));
        box.add_child(row);
    }
    return {actor: box, update: null};
}

function paletteCard(config) {
    const box = card(config, 'This look');
    const row = new St.BoxLayout({style_class: 'ricer-swatches'});
    for (const colour of config.palette ?? []) {
        if (COLOUR.test(colour))
            row.add_child(new St.Widget({style_class: 'ricer-swatch', style: `background-color: ${colour};`}));
    }
    box.add_child(row);
    if (Number.isInteger(config.seed))
        box.add_child(new St.Label({text: `seed ${config.seed}`, style_class: 'ricer-dim'}));
    return {actor: box, update: null};
}

const CARDS = {
    profile: profileCard, system: systemCard, progress: progressCard, fetch: fetchCard,
    palette: paletteCard,
};

export default class RicerExtension extends Extension {
    enable() {
        this._dateMenu = Main.panel.statusArea.dateMenu ?? null;
        this._state = {cpu: cpuTimes(), temperature: temperatureFile()};
        this._monitor = Gio.File.new_for_path(CONFIG).monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._monitorId = this._monitor.connect('changed', () => this._reloadSoon());
        this._apply();
    }

    disable() {
        if (this._reloadId)
            GLib.source_remove(this._reloadId);
        this._reloadId = null;
        this._monitor?.disconnect(this._monitorId);
        this._monitor?.cancel();
        this._monitor = this._monitorId = null;
        this._clearClock();
        this._clearMenu();
        this._dateMenu = this._state = null;
    }

    _reloadSoon() {
        if (this._reloadId)
            GLib.source_remove(this._reloadId);
        this._reloadId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RELOAD_DELAY_MS, () => {
            this._reloadId = null;
            this._apply();
            return GLib.SOURCE_REMOVE;
        });
    }

    _apply() {
        const config = readConfig();
        this._clearClock();
        this._clearMenu();
        if (!this._dateMenu)
            return;
        try {
            this._setClock(config.clock ?? {});
            this._setMenu(config);
        } catch (error) {
            // a shell laid out differently from the one this was written for: leave it stock
            console.error(`ricer: ${error}`);
            this._clearClock();
            this._clearMenu();
        }
    }

    // -- where the clock is ----------------------------------------------------------------

    _setClock(clock) {
        const stock = this._dateMenu._clockDisplay;
        const box = stock?.get_parent();
        if (!box || !clock.form || clock.form === 'full')
            return;
        if (clock.form === 'glyph') {
            this._clock = new St.Icon({
                icon_name: 'x-office-calendar-symbolic',
                style_class: 'system-status-icon ricer-clock-glyph',
                y_align: CENTER,
            });
        } else if (typeof clock.format === 'string' && clock.format) {
            const label = new St.Label({style_class: 'clock', y_align: CENTER});
            label.clutter_text.y_align = CENTER;
            label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            const update = () => {
                label.text = GLib.DateTime.new_now_local().format(clock.format) ?? '';
            };
            this._wallClock = this._dateMenu._clock ?? null;
            this._tickId = this._wallClock?.connect('notify::clock', update) ?? null;
            update();
            this._clock = label;
        } else {
            return;
        }
        box.insert_child_above(this._clock, stock);
        stock.hide();
        this._stockClock = stock;
    }

    _clearClock() {
        if (this._tickId)
            this._wallClock.disconnect(this._tickId);
        this._wallClock = this._tickId = null;
        this._clock?.destroy();
        this._clock = null;
        this._stockClock?.show();
        this._stockClock = null;
    }

    // -- the menu that opens from it -------------------------------------------------------

    _setMenu(config) {
        const names = (Array.isArray(config.menu) ? config.menu : []).filter(name => name in CARDS);
        const area = this._dateMenu._calendar?.get_parent()?.get_parent();
        if (!names.length || !area)
            return;
        this._column = new St.BoxLayout({
            vertical: true, style_class: 'ricer-dash', y_align: Clutter.ActorAlign.START,
        });
        this._updates = [];
        for (const name of names) {
            const {actor, update} = CARDS[name](config, this._state);
            this._column.add_child(actor);
            if (update)
                this._updates.push(update);
        }
        area.add_child(this._column);

        const menu = this._dateMenu.menu;
        this._menu = menu;
        this._openId = menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._startUpdates();
            else
                this._stopUpdates();
        });
        if (menu.isOpen)
            this._startUpdates();
    }

    _startUpdates() {
        this._stopUpdates();
        const refresh = () => this._updates.forEach(update => update());
        refresh();
        this._refreshId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, REFRESH_SECONDS, () => {
            refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopUpdates() {
        if (this._refreshId)
            GLib.source_remove(this._refreshId);
        this._refreshId = null;
    }

    _clearMenu() {
        this._stopUpdates();
        if (this._openId)
            this._menu.disconnect(this._openId);
        this._menu = this._openId = null;
        this._column?.destroy();
        this._column = null;
        this._updates = [];
    }
}
