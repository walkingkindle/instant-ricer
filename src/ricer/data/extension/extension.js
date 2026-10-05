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
import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';

const CONFIG = GLib.build_filenamev([GLib.get_user_config_dir(), 'ricer', 'shell.json']);
const REFRESH_SECONDS = 2;           // how often the cards update, and only while the menu is open
const RELOAD_DELAY_MS = 150;         // a rewrite of the file arrives as several events
const PROCESSES_EVERY = 3;           // refreshes between two looks at what is running
const PEAK_FLOOR = 1048576;          // bytes a second that fill a network meter at the least
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
        this._name = new St.Label({text: name, style_class: 'ricer-key', y_align: CENTER});
        this.actor.add_child(this._name);
        this.actor.add_child(this._track);
        this.actor.add_child(this._value);
    }

    setName(name) {
        this._name.text = name;
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

// The first battery's charge as a fraction, or null on a machine without one.
function batteryFile() {
    for (const name of ['BAT0', 'BAT1', 'BATT', 'CMB0']) {
        const path = `/sys/class/power_supply/${name}/capacity`;
        if (readText(path) !== null)
            return path;
    }
    return null;
}

// Bytes received and sent over every interface but the loopback, since boot.
function networkBytes() {
    let down = 0, up = 0;
    for (const line of (readText('/proc/net/dev') ?? '').split('\n').slice(2)) {
        const [name, rest] = line.split(':');
        if (!rest || name.trim() === 'lo')
            continue;
        const fields = rest.trim().split(/\s+/).map(Number);
        down += fields[0] || 0;
        up += fields[8] || 0;
    }
    return {down, up, time: GLib.get_monotonic_time()};
}

function rate(bytes) {
    if (bytes >= 1048576)
        return `${(bytes / 1048576).toFixed(1)}M`;
    return bytes >= 1024 ? `${Math.round(bytes / 1024)}K` : `${Math.round(bytes)}B`;
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
    const charge = state.battery ? new Meter('Battery') : null;
    for (const meter of [cpu, ram, heat, drive, charge]) {
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
        const charged = charge ? parseInt(readText(state.battery) ?? '') / 100 : NaN;
        if (Number.isFinite(charged))
            charge.set(charged, percent(charged));
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

function clockCard(config) {
    const box = card(config, null);
    const time = new St.Label({style_class: 'ricer-bigtime'});
    const date = new St.Label({style_class: 'ricer-dim'});
    box.add_child(time);
    box.add_child(date);
    const format = typeof config.time_format === 'string' ? config.time_format : '%H:%M';
    const update = () => {
        const now = GLib.DateTime.new_now_local();
        time.text = (now.format(format) ?? '').trim();
        date.text = now.format('%A, %-d %B') ?? '';
    };
    return {actor: box, update};
}

function networkCard(config, state) {
    const box = card(config, 'Network');
    const down = new Meter('Down'), up = new Meter('Up');
    box.add_child(down.actor);
    box.add_child(up.actor);
    let peak = PEAK_FLOOR;
    const update = () => {
        const now = networkBytes(), before = state.network;
        state.network = now;
        const seconds = before ? (now.time - before.time) / 1e6 : 0;
        if (seconds <= 0)
            return;
        const received = Math.max(0, now.down - before.down) / seconds;
        const sent = Math.max(0, now.up - before.up) / seconds;
        peak = Math.max(peak, received, sent);
        down.set(received / peak, rate(received));
        up.set(sent / peak, rate(sent));
    };
    return {actor: box, update};
}

// What uses the most memory, with the processes of one program counted together.
function processesCard(config, state) {
    const box = card(config, 'Most memory');
    const meters = [];
    for (let index = 0; index < 4; index++) {
        const meter = new Meter('');
        meter.actor.add_style_class_name('ricer-process');
        meters.push(meter);
        box.add_child(meter.actor);
    }
    let turn = 0;
    const show = text => {
        const total = memory()?.total ?? 0, used = new Map();
        for (const line of text.split('\n')) {
            const match = /^\s*(\d+)\s+(.+)$/.exec(line);
            if (match)
                used.set(match[2], (used.get(match[2]) ?? 0) + Number(match[1]));
        }
        const top = [...used.entries()].sort((a, b) => b[1] - a[1]).slice(0, meters.length);
        meters.forEach((meter, index) => {
            const [name, kb] = top[index] ?? ['', 0];
            meter.setName(name);
            meter.set(total ? kb / total : 0, kb ? `${(kb / 1048576).toFixed(1)}G` : '');
        });
    };
    const update = () => {
        if (turn++ % PROCESSES_EVERY)
            return;
        try {
            const ps = Gio.Subprocess.new(['ps', '-eo', 'rss=,comm='],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            ps.communicate_utf8_async(null, null, (_ps, result) => {
                try {
                    const [, text] = ps.communicate_utf8_finish(result);
                    if (state.alive && text)
                        show(text);
                } catch {
                    // no reading this time
                }
            });
        } catch {
            // no ps on this machine: the card stays empty
        }
    };
    return {actor: box, update};
}

function powerCard(config, _state, close) {
    const box = card(config, null);
    const row = new St.BoxLayout({style_class: 'ricer-actions', x_align: CENTER, x_expand: true});
    const actions = SystemActions.getDefault();
    const buttons = [
        ['system-lock-screen-symbolic', 'Lock', 'canLockScreen', () => actions.activateLockScreen()],
        ['weather-clear-night-symbolic', 'Suspend', 'canSuspend', () => actions.activateSuspend()],
        ['system-log-out-symbolic', 'Log out', 'canLogout', () => actions.activateLogout()],
        ['system-reboot-symbolic', 'Restart', 'canRestart', () => actions.activateRestart()],
        ['system-shutdown-symbolic', 'Power off', 'canPowerOff', () => actions.activatePowerOff()],
    ];
    for (const [icon, name, allowed, run] of buttons) {
        if (!actions[allowed])
            continue;
        const button = new St.Button({
            style_class: 'ricer-action', can_focus: true, accessible_name: name,
            child: new St.Icon({icon_name: icon}),
        });
        button.connect('clicked', () => {
            close();
            run();
        });
        row.add_child(button);
    }
    box.add_child(row);
    return {actor: box, update: null};
}

const CARDS = {
    clock: clockCard, profile: profileCard, system: systemCard, network: networkCard,
    processes: processesCard, progress: progressCard, fetch: fetchCard, palette: paletteCard,
    power: powerCard,
};

export default class RicerExtension extends Extension {
    enable() {
        this._dateMenu = Main.panel.statusArea.dateMenu ?? null;
        this._state = {
            cpu: cpuTimes(), temperature: temperatureFile(), battery: batteryFile(),
            network: networkBytes(), alive: true,
        };
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
        this._state.alive = false;                           // for a reading still on its way
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
        const calendarColumn = this._dateMenu._calendar?.get_parent();
        const area = calendarColumn?.get_parent();
        if (!names.length || !area)
            return;
        const menu = this._dateMenu.menu;
        const layout = config.layout;
        this._column = new St.BoxLayout({
            vertical: true, y_align: Clutter.ActorAlign.START,
            style_class: layout === 'under' ? 'ricer-dash-under' : 'ricer-dash',
        });
        this._updates = [];
        for (const name of names) {
            const {actor, update} = CARDS[name](config, this._state, () => menu.close());
            this._column.add_child(actor);
            if (update)
                this._updates.push(update);
        }
        // where the cards go, and which of GNOME's own parts make room for them
        const displays = this._dateMenu._displaysSection;
        if (layout === 'replace') {
            this._hide(calendarColumn);
            area.add_child(this._column);
        } else if (layout === 'under' && displays) {
            this._hide(displays);
            calendarColumn.add_child(this._column);
        } else if (layout === 'first') {
            this._column.add_style_class_name('ricer-dash-first');
            area.insert_child_at_index(this._column, 0);
        } else {
            area.add_child(this._column);
        }

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

    _hide(actor) {
        if (actor.visible) {
            actor.hide();
            this._hidden.push(actor);
        }
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
        (this._hidden ?? []).forEach(actor => actor.show());
        this._hidden = [];
    }
}
