const manifest = {"name":"DualSense Haptics"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

var DefaultContext = {
  color: undefined,
  size: undefined,
  className: undefined,
  style: undefined,
  attr: undefined
};
var IconContext = SP_REACT.createContext && /*#__PURE__*/SP_REACT.createContext(DefaultContext);

var _excluded = ["attr", "size", "title"];
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), true).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: true, configurable: true, writable: true }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == typeof i ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != typeof t || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r); if ("object" != typeof i) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function Tree2Element(tree) {
  return tree && tree.map((node, i) => /*#__PURE__*/SP_REACT.createElement(node.tag, _objectSpread({
    key: i
  }, node.attr), Tree2Element(node.child)));
}
function GenIcon(data) {
  return props => /*#__PURE__*/SP_REACT.createElement(IconBase, _extends({
    attr: _objectSpread({}, data.attr)
  }, props), Tree2Element(data.child));
}
function IconBase(props) {
  var elem = conf => {
    var attr = props.attr,
      size = props.size,
      title = props.title,
      svgProps = _objectWithoutProperties(props, _excluded);
    var computedSize = size || conf.size || "1em";
    var className;
    if (conf.className) className = conf.className;
    if (props.className) className = (className ? className + " " : "") + props.className;
    return /*#__PURE__*/SP_REACT.createElement("svg", _extends({
      stroke: "currentColor",
      fill: "currentColor",
      strokeWidth: "0"
    }, conf.attr, attr, svgProps, {
      className: className,
      style: _objectSpread(_objectSpread({
        color: props.color || conf.color
      }, conf.style), props.style),
      height: computedSize,
      width: computedSize,
      xmlns: "http://www.w3.org/2000/svg"
    }), title && /*#__PURE__*/SP_REACT.createElement("title", null, title), props.children);
  };
  return IconContext !== undefined ? /*#__PURE__*/SP_REACT.createElement(IconContext.Consumer, null, conf => elem(conf)) : elem(DefaultContext);
}

// THIS FILE IS AUTO GENERATED
function FaGamepad (props) {
  return GenIcon({"attr":{"viewBox":"0 0 640 512"},"child":[{"tag":"path","attr":{"d":"M480.07 96H160a160 160 0 1 0 114.24 272h91.52A160 160 0 1 0 480.07 96zM248 268a12 12 0 0 1-12 12h-52v52a12 12 0 0 1-12 12h-24a12 12 0 0 1-12-12v-52H84a12 12 0 0 1-12-12v-24a12 12 0 0 1 12-12h52v-52a12 12 0 0 1 12-12h24a12 12 0 0 1 12 12v52h52a12 12 0 0 1 12 12zm216 76a40 40 0 1 1 40-40 40 40 0 0 1-40 40zm64-96a40 40 0 1 1 40-40 40 40 0 0 1-40 40z"},"child":[]}]})(props);
}

const startEngine = callable("start_engine");
const stopEngine = callable("stop_engine");
const isRunning = callable("is_running");
const getStatus = callable("get_status");
const listPresets = callable("list_presets");
const getActivePreset = callable("get_active_preset");
const applyPreset = callable("apply_preset");
const getGain = callable("get_gain");
const setGain = callable("set_gain");
const listProfiles = callable("list_profiles");
const getActiveProfile = callable("get_active_profile");
const applyProfile = callable("apply_profile");
const listTriggerPresets = callable("list_trigger_presets");
const getTriggerPreset = callable("get_trigger_preset");
const applyTriggerPreset = callable("apply_trigger_preset");
const turnOffTrigger = callable("turn_off_trigger");
const getDirectAudio = callable("get_direct_audio");
const setDirectAudioEnabled = callable("set_direct_audio_enabled");
const setDirectAudioBtEnabled = callable("set_direct_audio_bt_enabled");
const PRESET_LABELS = {
    balanced: "Balanced",
    cinema: "Cinema",
    music: "Music",
    voice: "Voice & Podcasts",
    max: "Maximum Sensitivity",
};
const TRIGGER_LABELS = {
    off: "Off",
    soft: "Soft Resistance",
    hard_wall: "Hard Wall",
    weapon: "Weapon Trigger",
    bow: "Bow",
    machine: "Machine Gun",
    clicker: "Clicker",
    gallop: "Gallop",
    strong_click: "Strong Click",
    engine_hum: "Engine Hum",
};
function TriggerRow({ side, label }) {
    const [options, setOptions] = SP_REACT.useState([]);
    const [selected, setSelected] = SP_REACT.useState("off");
    SP_REACT.useEffect(() => {
        (async () => {
            const presets = await listTriggerPresets();
            setOptions(["off", ...presets]);
            const active = await getTriggerPreset(side);
            setSelected(active ?? "off");
        })();
    }, []);
    const onChange = async (option) => {
        setSelected(option.data);
        if (option.data === "off")
            await turnOffTrigger(side);
        else
            await applyTriggerPreset(option.data, side);
    };
    return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: label, rgOptions: options.map((p) => ({ data: p, label: TRIGGER_LABELS[p] ?? p })), selectedOption: selected, onChange: onChange }) }));
}
function Content() {
    const [enabled, setEnabled] = SP_REACT.useState(false);
    const [status, setStatus] = SP_REACT.useState(null);
    const [connection, setConnection] = SP_REACT.useState(null);
    const [battery, setBattery] = SP_REACT.useState(null);
    const [presetList, setPresetList] = SP_REACT.useState([]);
    const [activePreset, setActivePreset] = SP_REACT.useState(null);
    const [profileList, setProfileList] = SP_REACT.useState([]);
    const [activeProfile, setActiveProfile] = SP_REACT.useState(null);
    const [gain, setGainValue] = SP_REACT.useState(1.0);
    SP_REACT.useEffect(() => {
        (async () => {
            setEnabled(await isRunning());
            setPresetList(await listPresets());
            setActivePreset(await getActivePreset());
            setProfileList(await listProfiles());
            setActiveProfile(await getActiveProfile());
            setGainValue(await getGain());
        })();
        const interval = setInterval(async () => {
            const s = await getStatus();
            setStatus(s.status);
            setConnection(s.connection);
            setBattery(s.battery_percent);
            setEnabled(s.running);
        }, 2000);
        return () => clearInterval(interval);
    }, []);
    const onToggle = async (value) => {
        setEnabled(value);
        if (value)
            await startEngine();
        else
            await stopEngine();
    };
    const onPresetChange = async (option) => {
        setActivePreset(option.data);
        setActiveProfile(null);
        await applyPreset(option.data);
    };
    const onProfileChange = async (option) => {
        setActiveProfile(option.data);
        setActivePreset(null);
        await applyProfile(option.data);
    };
    const onGainChange = async (value) => {
        setGainValue(value);
        await setGain(value);
    };
    const connectionLabel = connection === "usb" ? "USB" : connection === "bluetooth" ? "Bluetooth" : "—";
    const statusLabel = status === "connected" ? "Connected" : status === "searching" ? "Searching…" : status ?? "—";
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "DualSense Haptics", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Vibration", checked: enabled, onChange: onToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.85em", opacity: 0.75 }, children: [SP_JSX.jsxs("span", { children: [statusLabel, " \u00B7 ", connectionLabel] }), SP_JSX.jsx("span", { children: battery !== null ? `${battery}%` : "" })] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: "Preset", rgOptions: presetList.map((p) => ({ data: p, label: PRESET_LABELS[p] ?? p })), selectedOption: activePreset, onChange: onPresetChange }) }), profileList.length > 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: "Profile", rgOptions: profileList.map((p) => ({ data: p, label: p })), selectedOption: activeProfile, onChange: onProfileChange }) })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: "Strength", value: gain, min: 0.2, max: 2.5, step: 0.05, notchTicksVisible: false, onChange: onGainChange }) })] }));
}
function TriggersSection() {
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "Adaptive Triggers", children: [SP_JSX.jsx(TriggerRow, { side: "left", label: "Left (L2)" }), SP_JSX.jsx(TriggerRow, { side: "right", label: "Right (R2)" })] }));
}
function DirectAudioSection() {
    const [directAudio, setDirectAudioState] = SP_REACT.useState({
        enabled: true,
        gain: 5.0,
        bt_enabled: false,
    });
    SP_REACT.useEffect(() => {
        (async () => setDirectAudioState(await getDirectAudio()))();
    }, []);
    const onUsbToggle = async (value) => {
        setDirectAudioState((d) => ({ ...d, enabled: value }));
        await setDirectAudioEnabled(value);
    };
    const onBtToggle = async (value) => {
        setDirectAudioState((d) => ({ ...d, bt_enabled: value }));
        await setDirectAudioBtEnabled(value);
    };
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "Direct Audio", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "USB (literal audio on the motors)", checked: directAudio.enabled, onChange: onUsbToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Bluetooth (experimental, needs SAxense)", checked: directAudio.bt_enabled, onChange: onBtToggle }) })] }));
}
var index = definePlugin(() => {
    return {
        name: "DualSense Haptics",
        titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "DualSense Haptics" }),
        content: (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(Content, {}), SP_JSX.jsx(TriggersSection, {}), SP_JSX.jsx(DirectAudioSection, {})] })),
        icon: SP_JSX.jsx(FaGamepad, {}),
        onDismount() { },
    };
});

export { index as default };
//# sourceMappingURL=index.js.map
