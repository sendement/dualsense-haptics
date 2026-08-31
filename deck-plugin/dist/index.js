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

// Auto-extracted from ../../i18n.py (desktop app) + a handful of Decky-only
// keys - regenerate by re-running the script in the commit that added this
// file if the desktop translations change.
const LANGUAGES = [["en", "English"], ["ru", "Русский"], ["zh", "中文"], ["es", "Español"], ["de", "Deutsch"], ["fr", "Français"], ["ja", "日本語"], ["pt", "Português"], ["ko", "한국어"]];
const STRINGS = {
    "en": {
        "home_vibration": "Vibration",
        "status_searching": "Searching for controller…",
        "status_connected": "Connected",
        "status_overridden": "Overridden by Steam",
        "battery_unknown": "—",
        "btn_apply": "Apply",
        "triggers_title": "Adaptive Triggers",
        "trigger_left_title": "Left Trigger (L2)",
        "trigger_right_title": "Right Trigger (R2)",
        "direct_audio_checkbox": "Play audio straight through the motors",
        "direct_audio_bt_checkbox": "Enable over Bluetooth (experimental)",
        "label_bt_chunk_ms": "Audio chunk size (ms)",
        "led_visualizer_title": "Immersive Lighting",
        "led_visualizer_checkbox": "Enable Immersive Lighting",
        "label_led_attack": "Reaction Speed",
        "label_led_release": "Fade Speed",
        "label_led_gamma": "Peak Contrast",
        "label_led_bass_priority": "Bass Priority",
        "game_profiles_title": "Game Profiles",
        "label_direct_gain": "Strength",
        "group_language": "Language",
        "trigger_custom_title": "Custom Effect",
        "label_trigger_off": "Off",
        "trig_mode_off": "Off",
        "trig_mode_feedback": "Feedback",
        "trig_mode_weapon": "Weapon",
        "trig_mode_bow": "Bow",
        "trig_mode_machine": "Machine Gun",
        "trig_mode_galloping": "Galloping",
        "trig_mode_vibration": "Vibration",
        "trig_mode_feedback_raw": "Feedback (Raw)",
        "trig_mode_vibration_raw": "Vibration (Raw)",
        "trig_param_position": "Position",
        "trig_param_strength": "Strength",
        "trig_param_start": "Start",
        "trig_param_end": "End",
        "trig_param_snap": "Snap",
        "trig_param_strength_a": "Strength A",
        "trig_param_strength_b": "Strength B",
        "trig_param_frequency": "Frequency",
        "trig_param_period": "Period",
        "trig_param_first_foot": "First Beat",
        "trig_param_second_foot": "Second Beat",
        "trig_param_amplitude": "Amplitude",
        "preset_balanced_label": "Balanced",
        "preset_cinema_label": "Cinema",
        "preset_music_label": "Music",
        "preset_voice_label": "Voice & Podcasts",
        "preset_max_label": "Maximum Sensitivity",
        "trigger_soft_label": "Soft Resistance",
        "trigger_hard_wall_label": "Hard Wall",
        "trigger_weapon_label": "Weapon Trigger",
        "trigger_bow_label": "Bow",
        "trigger_machine_label": "Machine Gun",
        "trigger_clicker_label": "Ratchet",
        "trigger_gallop_label": "Gallop",
        "trigger_strong_click_label": "Strong Click",
        "trigger_engine_hum_label": "Engine Hum",
        "preset_label": "Preset",
        "profile_label": "Profile",
        "direct_audio_title": "Direct Audio",
        "mode_label": "Mode",
        "label_master_gain": "Overall Vibration Volume",
        "slider_lo": "Trigger Threshold (lo)",
        "slider_lo_hint": "Below this level the motor stays silent.",
        "slider_hi": "Full Strength Threshold (hi)",
        "slider_hi_hint": "At this level and above — full strength. Lower = more sensitive.",
        "slider_attack": "Attack",
        "slider_attack_hint": "How fast the motor reaches its target strength.",
        "slider_release": "Release",
        "slider_release_hint": "How fast the motor fades out. Higher = sharper/shorter response.",
        "slider_gamma": "Contrast (gamma)",
        "slider_gamma_hint": "Above 1 — reacts only to loud sound. Below 1 — more sensitive to quiet sound.",
        "slider_ceil_attack": "Background Suppression: Speed",
        "slider_ceil_attack_hint": "How fast a constant background is suppressed. Lower = more aggressive.",
        "slider_ceil_release": "Background Suppression: Memory",
        "slider_ceil_release_hint": "How long the background level is remembered between spikes.",
        "group_bass": "Bass (strong motor)",
        "group_treble": "Treble (weak motor)",
        "btn_dpad": "D-Pad",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (press)",
        "btn_l3": "L3 (stick)",
        "btn_share": "Share / Create",
        "btn_cross": "Cross (✕)",
        "btn_circle": "Circle (○)",
        "btn_triangle": "Triangle (△)",
        "btn_square": "Square (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (press)",
        "btn_r3": "R3 (stick)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Left Side",
        "group_right_side": "Right Side",
        "button_haptic_title": "Button Vibration",
        "button_haptic_hint": "While a button is held, its motor buzzes continuously — independent of sound, and mixed with the normal audio vibration. Left-side buttons lightly buzz the strong/left motor, right-side buttons the weak/right motor, each at its own strength.",
        "collapse_show": "Show settings",
        "collapse_hide": "Hide settings",
        "game_profiles_enabled_checkbox": "Use game profile",
    },
    "ru": {
        "home_vibration": "Вибрация",
        "status_searching": "Поиск контроллера...",
        "status_connected": "Подключено",
        "status_overridden": "Перехвачено Steam",
        "battery_unknown": "—",
        "btn_apply": "Применить",
        "triggers_title": "Адаптивные триггеры",
        "trigger_left_title": "Левый триггер (L2)",
        "trigger_right_title": "Правый триггер (R2)",
        "direct_audio_checkbox": "Играть звук напрямую через моторы",
        "direct_audio_bt_checkbox": "Включить по Bluetooth (экспериментально)",
        "label_bt_chunk_ms": "Размер аудио-чанка (мс)",
        "led_visualizer_title": "Иммерсивная подсветка",
        "led_visualizer_checkbox": "Включить иммерсивную подсветку",
        "label_led_attack": "Скорость реакции",
        "label_led_release": "Скорость затухания",
        "label_led_gamma": "Контраст пиков",
        "label_led_bass_priority": "Приоритет баса",
        "game_profiles_title": "Профили под игры",
        "label_direct_gain": "Сила",
        "group_language": "Язык",
        "trigger_custom_title": "Свой эффект",
        "label_trigger_off": "Выключен",
        "trig_mode_off": "Выключен",
        "trig_mode_feedback": "Сопротивление",
        "trig_mode_weapon": "Оружие",
        "trig_mode_bow": "Лук",
        "trig_mode_machine": "Пулемёт",
        "trig_mode_galloping": "Галоп",
        "trig_mode_vibration": "Вибрация",
        "trig_mode_feedback_raw": "Сопротивление (по зонам)",
        "trig_mode_vibration_raw": "Вибрация (по зонам)",
        "trig_param_position": "Позиция",
        "trig_param_strength": "Сила",
        "trig_param_start": "Начало",
        "trig_param_end": "Конец",
        "trig_param_snap": "Резкость",
        "trig_param_strength_a": "Сила A",
        "trig_param_strength_b": "Сила B",
        "trig_param_frequency": "Частота",
        "trig_param_period": "Период",
        "trig_param_first_foot": "Первый удар",
        "trig_param_second_foot": "Второй удар",
        "trig_param_amplitude": "Амплитуда",
        "preset_balanced_label": "Сбалансированный",
        "preset_cinema_label": "Кино",
        "preset_music_label": "Музыка",
        "preset_voice_label": "Голос и подкасты",
        "preset_max_label": "Максимальная чувствительность",
        "trigger_soft_label": "Мягкое сопротивление",
        "trigger_hard_wall_label": "Жёсткий стопор",
        "trigger_weapon_label": "Курок оружия",
        "trigger_bow_label": "Лук",
        "trigger_machine_label": "Пулемёт",
        "trigger_clicker_label": "Трещотка",
        "trigger_gallop_label": "Галоп",
        "trigger_strong_click_label": "Сильный щелчок",
        "trigger_engine_hum_label": "Гул двигателя",
        "preset_label": "Пресет",
        "profile_label": "Профиль",
        "direct_audio_title": "Прямой звук",
        "mode_label": "Режим",
        "label_master_gain": "Общая громкость вибрации",
        "slider_lo": "Порог срабатывания (lo)",
        "slider_lo_hint": "Ниже этого уровня мотор молчит.",
        "slider_hi": "Порог полной силы (hi)",
        "slider_hi_hint": "На этом уровне и выше — полная сила. Меньше = чувствительнее.",
        "slider_attack": "Атака",
        "slider_attack_hint": "Как быстро мотор выходит на нужную силу.",
        "slider_release": "Спад",
        "slider_release_hint": "Как быстро мотор затихает. Больше = резче/короче отклик.",
        "slider_gamma": "Контраст (гамма)",
        "slider_gamma_hint": "Больше 1 — реагирует только на громкое. Меньше 1 — чувствительнее к тихому.",
        "slider_ceil_attack": "Подавление фона: скорость",
        "slider_ceil_attack_hint": "Как быстро гасится постоянный фон. Меньше = агрессивнее.",
        "slider_ceil_release": "Подавление фона: память",
        "slider_ceil_release_hint": "Как долго помнится уровень фона между всплесками.",
        "group_bass": "Бас (сильный мотор)",
        "group_treble": "Верхи (лёгкий мотор)",
        "btn_dpad": "Крестовина",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (нажатие)",
        "btn_l3": "L3 (стик)",
        "btn_share": "Share / Create",
        "btn_cross": "Крест (✕)",
        "btn_circle": "Кружок (○)",
        "btn_triangle": "Треугольник (△)",
        "btn_square": "Квадрат (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (нажатие)",
        "btn_r3": "R3 (стик)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Левая сторона",
        "group_right_side": "Правая сторона",
        "button_haptic_title": "Вибрация кнопки",
        "button_haptic_hint": "Пока кнопка зажата, соответствующий мотор гудит постоянно — независимо от звука, и суммируется с обычной аудио-вибрацией. Кнопки левой стороны чуть подрагивают на сильном/левом моторе, правой — на лёгком/правом, каждая своей силой.",
        "collapse_show": "Показать настройки",
        "collapse_hide": "Скрыть настройки",
        "game_profiles_enabled_checkbox": "Использовать игровой профиль",
    },
    "zh": {
        "home_vibration": "振动",
        "status_searching": "正在搜索控制器…",
        "status_connected": "已连接",
        "status_overridden": "已被 Steam 接管",
        "battery_unknown": "—",
        "btn_apply": "应用",
        "triggers_title": "自适应扳机",
        "trigger_left_title": "左扳机 (L2)",
        "trigger_right_title": "右扳机 (R2)",
        "direct_audio_checkbox": "直接通过马达播放音频",
        "direct_audio_bt_checkbox": "通过蓝牙启用（实验性）",
        "label_bt_chunk_ms": "音频块大小（毫秒）",
        "led_visualizer_title": "沉浸式灯光",
        "led_visualizer_checkbox": "启用沉浸式灯光",
        "label_led_attack": "反应速度",
        "label_led_release": "衰减速度",
        "label_led_gamma": "峰值对比度",
        "label_led_bass_priority": "低音优先级",
        "game_profiles_title": "游戏配置",
        "label_direct_gain": "强度",
        "group_language": "语言",
        "trigger_custom_title": "自定义效果",
        "label_trigger_off": "已关闭",
        "trig_mode_off": "关闭",
        "trig_mode_feedback": "反馈阻力",
        "trig_mode_weapon": "武器",
        "trig_mode_bow": "弓箭",
        "trig_mode_machine": "机枪",
        "trig_mode_galloping": "疾驰",
        "trig_mode_vibration": "振动",
        "trig_mode_feedback_raw": "反馈阻力（分区）",
        "trig_mode_vibration_raw": "振动（分区）",
        "trig_param_position": "位置",
        "trig_param_strength": "强度",
        "trig_param_start": "起点",
        "trig_param_end": "终点",
        "trig_param_snap": "回弹力度",
        "trig_param_strength_a": "强度 A",
        "trig_param_strength_b": "强度 B",
        "trig_param_frequency": "频率",
        "trig_param_period": "周期",
        "trig_param_first_foot": "第一拍",
        "trig_param_second_foot": "第二拍",
        "trig_param_amplitude": "振幅",
        "preset_balanced_label": "均衡",
        "preset_cinema_label": "影院",
        "preset_music_label": "音乐",
        "preset_voice_label": "语音与播客",
        "preset_max_label": "最高灵敏度",
        "trigger_soft_label": "轻柔阻力",
        "trigger_hard_wall_label": "硬性止点",
        "trigger_weapon_label": "武器扳机",
        "trigger_bow_label": "弓箭",
        "trigger_machine_label": "机枪",
        "trigger_clicker_label": "棘轮",
        "trigger_gallop_label": "疾驰",
        "trigger_strong_click_label": "强力点击",
        "trigger_engine_hum_label": "引擎嗡鸣",
        "preset_label": "预设",
        "profile_label": "配置文件",
        "direct_audio_title": "直接音频",
        "mode_label": "模式",
        "label_master_gain": "总振动音量",
        "slider_lo": "触发阈值 (lo)",
        "slider_lo_hint": "低于此电平时马达保持静止。",
        "slider_hi": "满强度阈值 (hi)",
        "slider_hi_hint": "达到或超过此电平即为最大强度。数值越低越灵敏。",
        "slider_attack": "起振速度",
        "slider_attack_hint": "马达达到目标强度的速度。",
        "slider_release": "释放速度",
        "slider_release_hint": "马达衰减的速度。数值越大，响应越急促短暂。",
        "slider_gamma": "对比度 (gamma)",
        "slider_gamma_hint": "大于 1——只对响亮的声音有反应。小于 1——对轻声更敏感。",
        "slider_ceil_attack": "背景抑制：速度",
        "slider_ceil_attack_hint": "抑制持续背景噪音的速度。数值越低越激进。",
        "slider_ceil_release": "背景抑制：记忆时长",
        "slider_ceil_release_hint": "两次峰值之间记住背景电平的时长。",
        "group_bass": "低音（强马达）",
        "group_treble": "高音（弱马达）",
        "btn_dpad": "方向键",
        "btn_l1": "L1",
        "btn_l2_press": "L2（按下）",
        "btn_l3": "L3（摇杆按下）",
        "btn_share": "分享/创建",
        "btn_cross": "✕（叉）",
        "btn_circle": "○（圈）",
        "btn_triangle": "△（三角）",
        "btn_square": "□（方块）",
        "btn_r1": "R1",
        "btn_r2_press": "R2（按下）",
        "btn_r3": "R3（摇杆按下）",
        "btn_options": "选项",
        "btn_ps": "PS",
        "group_left_side": "左侧",
        "group_right_side": "右侧",
        "button_haptic_title": "按键振动",
        "button_haptic_hint": "按住按键时，对应马达会持续振动——与声音无关，并与正常的音频振动叠加。左侧按键轻微振动强马达（左），右侧按键振动弱马达（右），各自使用自己的强度。",
        "collapse_show": "显示设置",
        "collapse_hide": "隐藏设置",
        "game_profiles_enabled_checkbox": "使用游戏专属配置",
    },
    "es": {
        "home_vibration": "Vibración",
        "status_searching": "Buscando mando…",
        "status_connected": "Conectado",
        "status_overridden": "Anulado por Steam",
        "battery_unknown": "—",
        "btn_apply": "Aplicar",
        "triggers_title": "Gatillos adaptativos",
        "trigger_left_title": "Gatillo izquierdo (L2)",
        "trigger_right_title": "Gatillo derecho (R2)",
        "direct_audio_checkbox": "Reproducir audio directamente en los motores",
        "direct_audio_bt_checkbox": "Activar por Bluetooth (experimental)",
        "label_bt_chunk_ms": "Tamaño del bloque de audio (ms)",
        "led_visualizer_title": "Iluminación inmersiva",
        "led_visualizer_checkbox": "Activar iluminación inmersiva",
        "label_led_attack": "Velocidad de reacción",
        "label_led_release": "Velocidad de desvanecimiento",
        "label_led_gamma": "Contraste de picos",
        "label_led_bass_priority": "Prioridad de graves",
        "game_profiles_title": "Perfiles de juego",
        "label_direct_gain": "Intensidad",
        "group_language": "Idioma",
        "trigger_custom_title": "Efecto personalizado",
        "label_trigger_off": "Desactivado",
        "trig_mode_off": "Apagado",
        "trig_mode_feedback": "Resistencia",
        "trig_mode_weapon": "Arma",
        "trig_mode_bow": "Arco",
        "trig_mode_machine": "Ametralladora",
        "trig_mode_galloping": "Galope",
        "trig_mode_vibration": "Vibración",
        "trig_mode_feedback_raw": "Resistencia (por zonas)",
        "trig_mode_vibration_raw": "Vibración (por zonas)",
        "trig_param_position": "Posición",
        "trig_param_strength": "Fuerza",
        "trig_param_start": "Inicio",
        "trig_param_end": "Fin",
        "trig_param_snap": "Chasquido",
        "trig_param_strength_a": "Fuerza A",
        "trig_param_strength_b": "Fuerza B",
        "trig_param_frequency": "Frecuencia",
        "trig_param_period": "Periodo",
        "trig_param_first_foot": "Primer golpe",
        "trig_param_second_foot": "Segundo golpe",
        "trig_param_amplitude": "Amplitud",
        "preset_balanced_label": "Equilibrado",
        "preset_cinema_label": "Cine",
        "preset_music_label": "Música",
        "preset_voice_label": "Voz y podcasts",
        "preset_max_label": "Sensibilidad máxima",
        "trigger_soft_label": "Resistencia suave",
        "trigger_hard_wall_label": "Pared dura",
        "trigger_weapon_label": "Gatillo de arma",
        "trigger_bow_label": "Arco",
        "trigger_machine_label": "Ametralladora",
        "trigger_clicker_label": "Trinquete",
        "trigger_gallop_label": "Galope",
        "trigger_strong_click_label": "Clic fuerte",
        "trigger_engine_hum_label": "Zumbido de motor",
        "preset_label": "Preajuste",
        "profile_label": "Perfil",
        "direct_audio_title": "Audio directo",
        "mode_label": "Modo",
        "label_master_gain": "Volumen general de vibración",
        "slider_lo": "Umbral de activación (lo)",
        "slider_lo_hint": "Por debajo de este nivel el motor permanece en silencio.",
        "slider_hi": "Umbral de fuerza máxima (hi)",
        "slider_hi_hint": "En este nivel o superior, fuerza máxima. Menor = más sensible.",
        "slider_attack": "Ataque",
        "slider_attack_hint": "Qué tan rápido el motor alcanza su fuerza objetivo.",
        "slider_release": "Caída",
        "slider_release_hint": "Qué tan rápido se apaga el motor. Mayor = respuesta más brusca/corta.",
        "slider_gamma": "Contraste (gamma)",
        "slider_gamma_hint": "Mayor que 1: solo reacciona a sonidos fuertes. Menor que 1: más sensible a sonidos suaves.",
        "slider_ceil_attack": "Supresión de fondo: velocidad",
        "slider_ceil_attack_hint": "Qué tan rápido se suprime un fondo constante. Menor = más agresivo.",
        "slider_ceil_release": "Supresión de fondo: memoria",
        "slider_ceil_release_hint": "Cuánto tiempo se recuerda el nivel de fondo entre picos.",
        "group_bass": "Graves (motor fuerte)",
        "group_treble": "Agudos (motor débil)",
        "btn_dpad": "Cruceta",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (pulsación)",
        "btn_l3": "L3 (stick)",
        "btn_share": "Compartir / Crear",
        "btn_cross": "Cruz (✕)",
        "btn_circle": "Círculo (○)",
        "btn_triangle": "Triángulo (△)",
        "btn_square": "Cuadrado (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (pulsación)",
        "btn_r3": "R3 (stick)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Lado izquierdo",
        "group_right_side": "Lado derecho",
        "button_haptic_title": "Vibración de botones",
        "button_haptic_hint": "Mientras se mantiene pulsado un botón, su motor vibra continuamente, independientemente del sonido, y se mezcla con la vibración de audio normal. Los botones del lado izquierdo vibran ligeramente el motor fuerte/izquierdo, los del lado derecho el motor débil/derecho, cada uno con su propia intensidad.",
        "collapse_show": "Mostrar ajustes",
        "collapse_hide": "Ocultar ajustes",
        "game_profiles_enabled_checkbox": "Usar perfil por juego",
    },
    "de": {
        "home_vibration": "Vibration",
        "status_searching": "Suche nach Controller…",
        "status_connected": "Verbunden",
        "status_overridden": "Von Steam übersteuert",
        "battery_unknown": "—",
        "btn_apply": "Anwenden",
        "triggers_title": "Adaptive Trigger",
        "trigger_left_title": "Linker Trigger (L2)",
        "trigger_right_title": "Rechter Trigger (R2)",
        "direct_audio_checkbox": "Audio direkt über die Motoren abspielen",
        "direct_audio_bt_checkbox": "Über Bluetooth aktivieren (experimentell)",
        "label_bt_chunk_ms": "Audio-Chunkgröße (ms)",
        "led_visualizer_title": "Immersive Beleuchtung",
        "led_visualizer_checkbox": "Immersive Beleuchtung aktivieren",
        "label_led_attack": "Reaktionsgeschwindigkeit",
        "label_led_release": "Abklingzeit",
        "label_led_gamma": "Spitzen-Kontrast",
        "label_led_bass_priority": "Bass-Priorität",
        "game_profiles_title": "Spielprofile",
        "label_direct_gain": "Stärke",
        "group_language": "Sprache",
        "trigger_custom_title": "Eigener Effekt",
        "label_trigger_off": "Aus",
        "trig_mode_off": "Aus",
        "trig_mode_feedback": "Widerstand",
        "trig_mode_weapon": "Waffe",
        "trig_mode_bow": "Bogen",
        "trig_mode_machine": "Maschinengewehr",
        "trig_mode_galloping": "Galopp",
        "trig_mode_vibration": "Vibration",
        "trig_mode_feedback_raw": "Widerstand (Zonen)",
        "trig_mode_vibration_raw": "Vibration (Zonen)",
        "trig_param_position": "Position",
        "trig_param_strength": "Stärke",
        "trig_param_start": "Start",
        "trig_param_end": "Ende",
        "trig_param_snap": "Schnappkraft",
        "trig_param_strength_a": "Stärke A",
        "trig_param_strength_b": "Stärke B",
        "trig_param_frequency": "Frequenz",
        "trig_param_period": "Periode",
        "trig_param_first_foot": "Erster Schlag",
        "trig_param_second_foot": "Zweiter Schlag",
        "trig_param_amplitude": "Amplitude",
        "preset_balanced_label": "Ausgewogen",
        "preset_cinema_label": "Kino",
        "preset_music_label": "Musik",
        "preset_voice_label": "Stimme & Podcasts",
        "preset_max_label": "Maximale Empfindlichkeit",
        "trigger_soft_label": "Sanfter Widerstand",
        "trigger_hard_wall_label": "Harte Wand",
        "trigger_weapon_label": "Waffenabzug",
        "trigger_bow_label": "Bogen",
        "trigger_machine_label": "Maschinengewehr",
        "trigger_clicker_label": "Ratsche",
        "trigger_gallop_label": "Galopp",
        "trigger_strong_click_label": "Starkes Klicken",
        "trigger_engine_hum_label": "Motorbrummen",
        "preset_label": "Preset",
        "profile_label": "Profil",
        "direct_audio_title": "Direktes Audio",
        "mode_label": "Modus",
        "label_master_gain": "Gesamtlautstärke der Vibration",
        "slider_lo": "Ansprechschwelle (lo)",
        "slider_lo_hint": "Unterhalb dieses Pegels bleibt der Motor still.",
        "slider_hi": "Schwelle für volle Stärke (hi)",
        "slider_hi_hint": "Ab diesem Pegel volle Stärke. Niedriger = empfindlicher.",
        "slider_attack": "Attack",
        "slider_attack_hint": "Wie schnell der Motor seine Zielstärke erreicht.",
        "slider_release": "Release",
        "slider_release_hint": "Wie schnell der Motor ausklingt. Höher = schärfere/kürzere Reaktion.",
        "slider_gamma": "Kontrast (Gamma)",
        "slider_gamma_hint": "Über 1 — reagiert nur auf laute Geräusche. Unter 1 — empfindlicher bei leisen Geräuschen.",
        "slider_ceil_attack": "Hintergrundunterdrückung: Geschwindigkeit",
        "slider_ceil_attack_hint": "Wie schnell ein konstanter Hintergrund unterdrückt wird. Niedriger = aggressiver.",
        "slider_ceil_release": "Hintergrundunterdrückung: Gedächtnis",
        "slider_ceil_release_hint": "Wie lange der Hintergrundpegel zwischen Spitzen gespeichert bleibt.",
        "group_bass": "Bass (starker Motor)",
        "group_treble": "Höhen (schwacher Motor)",
        "btn_dpad": "Steuerkreuz",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (drücken)",
        "btn_l3": "L3 (Stick)",
        "btn_share": "Share / Create",
        "btn_cross": "Kreuz (✕)",
        "btn_circle": "Kreis (○)",
        "btn_triangle": "Dreieck (△)",
        "btn_square": "Quadrat (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (drücken)",
        "btn_r3": "R3 (Stick)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Linke Seite",
        "group_right_side": "Rechte Seite",
        "button_haptic_title": "Tasten-Vibration",
        "button_haptic_hint": "Solange eine Taste gedrückt gehalten wird, summt der zugehörige Motor durchgehend — unabhängig vom Ton, und gemischt mit der normalen Audio-Vibration. Tasten auf der linken Seite lassen leicht den starken/linken Motor summen, auf der rechten Seite den schwachen/rechten, jeweils mit eigener Stärke.",
        "collapse_show": "Einstellungen anzeigen",
        "collapse_hide": "Einstellungen ausblenden",
        "game_profiles_enabled_checkbox": "Spielprofil verwenden",
    },
    "fr": {
        "home_vibration": "Vibration",
        "status_searching": "Recherche de la manette…",
        "status_connected": "Connectée",
        "status_overridden": "Remplacé par Steam",
        "battery_unknown": "—",
        "btn_apply": "Appliquer",
        "triggers_title": "Gâchettes adaptatives",
        "trigger_left_title": "Gâchette gauche (L2)",
        "trigger_right_title": "Gâchette droite (R2)",
        "direct_audio_checkbox": "Jouer l'audio directement sur les moteurs",
        "direct_audio_bt_checkbox": "Activer par Bluetooth (expérimental)",
        "label_bt_chunk_ms": "Taille du bloc audio (ms)",
        "led_visualizer_title": "Éclairage immersif",
        "led_visualizer_checkbox": "Activer l'éclairage immersif",
        "label_led_attack": "Vitesse de réaction",
        "label_led_release": "Vitesse d'estompage",
        "label_led_gamma": "Contraste des pics",
        "label_led_bass_priority": "Priorité des graves",
        "game_profiles_title": "Profils de jeu",
        "label_direct_gain": "Intensité",
        "group_language": "Langue",
        "trigger_custom_title": "Effet personnalisé",
        "label_trigger_off": "Désactivée",
        "trig_mode_off": "Désactivé",
        "trig_mode_feedback": "Résistance",
        "trig_mode_weapon": "Arme",
        "trig_mode_bow": "Arc",
        "trig_mode_machine": "Mitrailleuse",
        "trig_mode_galloping": "Galop",
        "trig_mode_vibration": "Vibration",
        "trig_mode_feedback_raw": "Résistance (zones)",
        "trig_mode_vibration_raw": "Vibration (zones)",
        "trig_param_position": "Position",
        "trig_param_strength": "Force",
        "trig_param_start": "Début",
        "trig_param_end": "Fin",
        "trig_param_snap": "Claquement",
        "trig_param_strength_a": "Force A",
        "trig_param_strength_b": "Force B",
        "trig_param_frequency": "Fréquence",
        "trig_param_period": "Période",
        "trig_param_first_foot": "Premier temps",
        "trig_param_second_foot": "Second temps",
        "trig_param_amplitude": "Amplitude",
        "preset_balanced_label": "Équilibré",
        "preset_cinema_label": "Cinéma",
        "preset_music_label": "Musique",
        "preset_voice_label": "Voix et podcasts",
        "preset_max_label": "Sensibilité maximale",
        "trigger_soft_label": "Résistance douce",
        "trigger_hard_wall_label": "Butée dure",
        "trigger_weapon_label": "Gâchette d'arme",
        "trigger_bow_label": "Arc",
        "trigger_machine_label": "Mitrailleuse",
        "trigger_clicker_label": "Cliquet",
        "trigger_gallop_label": "Galop",
        "trigger_strong_click_label": "Clic fort",
        "trigger_engine_hum_label": "Ronronnement moteur",
        "preset_label": "Préréglage",
        "profile_label": "Profil",
        "direct_audio_title": "Audio direct",
        "mode_label": "Mode",
        "label_master_gain": "Volume global de vibration",
        "slider_lo": "Seuil de déclenchement (lo)",
        "slider_lo_hint": "En dessous de ce niveau, le moteur reste silencieux.",
        "slider_hi": "Seuil de pleine puissance (hi)",
        "slider_hi_hint": "À ce niveau et au-delà — pleine puissance. Plus bas = plus sensible.",
        "slider_attack": "Attaque",
        "slider_attack_hint": "Vitesse à laquelle le moteur atteint sa puissance cible.",
        "slider_release": "Chute",
        "slider_release_hint": "Vitesse à laquelle le moteur s'estompe. Plus élevé = réponse plus brève/nette.",
        "slider_gamma": "Contraste (gamma)",
        "slider_gamma_hint": "Supérieur à 1 — ne réagit qu'aux sons forts. Inférieur à 1 — plus sensible aux sons faibles.",
        "slider_ceil_attack": "Suppression du fond : vitesse",
        "slider_ceil_attack_hint": "Vitesse à laquelle un fond constant est supprimé. Plus bas = plus agressif.",
        "slider_ceil_release": "Suppression du fond : mémoire",
        "slider_ceil_release_hint": "Durée pendant laquelle le niveau de fond est mémorisé entre deux pics.",
        "group_bass": "Graves (moteur fort)",
        "group_treble": "Aigus (moteur faible)",
        "btn_dpad": "Croix directionnelle",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (appui)",
        "btn_l3": "L3 (stick)",
        "btn_share": "Share / Create",
        "btn_cross": "Croix (✕)",
        "btn_circle": "Rond (○)",
        "btn_triangle": "Triangle (△)",
        "btn_square": "Carré (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (appui)",
        "btn_r3": "R3 (stick)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Côté gauche",
        "group_right_side": "Côté droit",
        "button_haptic_title": "Vibration des boutons",
        "button_haptic_hint": "Tant qu'un bouton est maintenu, son moteur vibre en continu — indépendamment du son, et se mélange à la vibration audio normale. Les boutons de gauche font légèrement vibrer le moteur fort/gauche, ceux de droite le moteur faible/droit, chacun avec sa propre intensité.",
        "collapse_show": "Afficher les réglages",
        "collapse_hide": "Masquer les réglages",
        "game_profiles_enabled_checkbox": "Utiliser un profil de jeu",
    },
    "ja": {
        "home_vibration": "振動",
        "status_searching": "コントローラーを検索中…",
        "status_connected": "接続済み",
        "status_overridden": "Steamに上書きされています",
        "battery_unknown": "—",
        "btn_apply": "適用",
        "triggers_title": "アダプティブトリガー",
        "trigger_left_title": "左トリガー (L2)",
        "trigger_right_title": "右トリガー (R2)",
        "direct_audio_checkbox": "音声をモーターに直接再生する",
        "direct_audio_bt_checkbox": "Bluetoothで有効にする（実験的機能）",
        "label_bt_chunk_ms": "オーディオチャンクサイズ（ms）",
        "led_visualizer_title": "没入型ライティング",
        "led_visualizer_checkbox": "没入型ライティングを有効にする",
        "label_led_attack": "反応速度",
        "label_led_release": "減衰速度",
        "label_led_gamma": "ピークのコントラスト",
        "label_led_bass_priority": "低音優先度",
        "game_profiles_title": "ゲームプロファイル",
        "label_direct_gain": "強さ",
        "group_language": "言語",
        "trigger_custom_title": "カスタム効果",
        "label_trigger_off": "オフ",
        "trig_mode_off": "オフ",
        "trig_mode_feedback": "抵抗",
        "trig_mode_weapon": "武器",
        "trig_mode_bow": "弓",
        "trig_mode_machine": "マシンガン",
        "trig_mode_galloping": "ギャロップ",
        "trig_mode_vibration": "振動",
        "trig_mode_feedback_raw": "抵抗（ゾーン）",
        "trig_mode_vibration_raw": "振動（ゾーン）",
        "trig_param_position": "位置",
        "trig_param_strength": "強さ",
        "trig_param_start": "開始",
        "trig_param_end": "終了",
        "trig_param_snap": "スナップ",
        "trig_param_strength_a": "強さ A",
        "trig_param_strength_b": "強さ B",
        "trig_param_frequency": "周波数",
        "trig_param_period": "周期",
        "trig_param_first_foot": "1拍目",
        "trig_param_second_foot": "2拍目",
        "trig_param_amplitude": "振幅",
        "preset_balanced_label": "バランス",
        "preset_cinema_label": "シネマ",
        "preset_music_label": "音楽",
        "preset_voice_label": "音声・ポッドキャスト",
        "preset_max_label": "最大感度",
        "trigger_soft_label": "ソフトな抵抗",
        "trigger_hard_wall_label": "ハードウォール",
        "trigger_weapon_label": "ウェポントリガー",
        "trigger_bow_label": "ボウ",
        "trigger_machine_label": "マシンガン",
        "trigger_clicker_label": "ラチェット",
        "trigger_gallop_label": "ギャロップ",
        "trigger_strong_click_label": "強いクリック",
        "trigger_engine_hum_label": "エンジンのうなり",
        "preset_label": "プリセット",
        "profile_label": "プロファイル",
        "direct_audio_title": "ダイレクトオーディオ",
        "mode_label": "モード",
        "label_master_gain": "振動の全体音量",
        "slider_lo": "作動しきい値 (lo)",
        "slider_lo_hint": "このレベル未満ではモーターは動作しません。",
        "slider_hi": "最大強度しきい値 (hi)",
        "slider_hi_hint": "このレベル以上で最大強度になります。値が小さいほど高感度です。",
        "slider_attack": "アタック",
        "slider_attack_hint": "モーターが目標の強さに達する速さです。",
        "slider_release": "リリース",
        "slider_release_hint": "モーターが減衰する速さです。値が大きいほど反応が鋭く短くなります。",
        "slider_gamma": "コントラスト（ガンマ）",
        "slider_gamma_hint": "1より大きい — 大きな音にのみ反応します。1より小さい — 小さな音により敏感になります。",
        "slider_ceil_attack": "背景抑制：速度",
        "slider_ceil_attack_hint": "一定の背景音を抑制する速さです。値が小さいほど積極的になります。",
        "slider_ceil_release": "背景抑制：記憶時間",
        "slider_ceil_release_hint": "ピーク間で背景レベルを記憶しておく時間です。",
        "group_bass": "低音（強モーター）",
        "group_treble": "高音（弱モーター）",
        "btn_dpad": "十字キー",
        "btn_l1": "L1",
        "btn_l2_press": "L2（押し込み）",
        "btn_l3": "L3（スティック押し込み）",
        "btn_share": "シェア / クリエイト",
        "btn_cross": "✕（クロス）",
        "btn_circle": "○（サークル）",
        "btn_triangle": "△（トライアングル）",
        "btn_square": "□（スクエア）",
        "btn_r1": "R1",
        "btn_r2_press": "R2（押し込み）",
        "btn_r3": "R3（スティック押し込み）",
        "btn_options": "オプション",
        "btn_ps": "PS",
        "group_left_side": "左側",
        "group_right_side": "右側",
        "button_haptic_title": "ボタン振動",
        "button_haptic_hint": "ボタンを押している間、対応するモーターが音とは無関係に振動し続け、通常の音声振動と合成されます。左側のボタンは強い/左モーターを軽く振動させ、右側のボタンは弱い/右モーターを、それぞれ独自の強さで振動させます。",
        "collapse_show": "設定を表示",
        "collapse_hide": "設定を隠す",
        "game_profiles_enabled_checkbox": "ゲームプロファイルを使う",
    },
    "pt": {
        "home_vibration": "Vibração",
        "status_searching": "Procurando controle…",
        "status_connected": "Conectado",
        "status_overridden": "Sobreposto pelo Steam",
        "battery_unknown": "—",
        "btn_apply": "Aplicar",
        "triggers_title": "Gatilhos adaptativos",
        "trigger_left_title": "Gatilho esquerdo (L2)",
        "trigger_right_title": "Gatilho direito (R2)",
        "direct_audio_checkbox": "Reproduzir áudio diretamente nos motores",
        "direct_audio_bt_checkbox": "Ativar via Bluetooth (experimental)",
        "label_bt_chunk_ms": "Tamanho do bloco de áudio (ms)",
        "led_visualizer_title": "Iluminação imersiva",
        "led_visualizer_checkbox": "Ativar iluminação imersiva",
        "label_led_attack": "Velocidade de reação",
        "label_led_release": "Velocidade de esmaecimento",
        "label_led_gamma": "Contraste de picos",
        "label_led_bass_priority": "Prioridade dos graves",
        "game_profiles_title": "Perfis de jogo",
        "label_direct_gain": "Intensidade",
        "group_language": "Idioma",
        "trigger_custom_title": "Efeito personalizado",
        "label_trigger_off": "Desligado",
        "trig_mode_off": "Desligado",
        "trig_mode_feedback": "Resistência",
        "trig_mode_weapon": "Arma",
        "trig_mode_bow": "Arco",
        "trig_mode_machine": "Metralhadora",
        "trig_mode_galloping": "Galope",
        "trig_mode_vibration": "Vibração",
        "trig_mode_feedback_raw": "Resistência (zonas)",
        "trig_mode_vibration_raw": "Vibração (zonas)",
        "trig_param_position": "Posição",
        "trig_param_strength": "Força",
        "trig_param_start": "Início",
        "trig_param_end": "Fim",
        "trig_param_snap": "Estalo",
        "trig_param_strength_a": "Força A",
        "trig_param_strength_b": "Força B",
        "trig_param_frequency": "Frequência",
        "trig_param_period": "Período",
        "trig_param_first_foot": "Primeira batida",
        "trig_param_second_foot": "Segunda batida",
        "trig_param_amplitude": "Amplitude",
        "preset_balanced_label": "Equilibrado",
        "preset_cinema_label": "Cinema",
        "preset_music_label": "Música",
        "preset_voice_label": "Voz e podcasts",
        "preset_max_label": "Sensibilidade máxima",
        "trigger_soft_label": "Resistência suave",
        "trigger_hard_wall_label": "Parede rígida",
        "trigger_weapon_label": "Gatilho de arma",
        "trigger_bow_label": "Arco",
        "trigger_machine_label": "Metralhadora",
        "trigger_clicker_label": "Catraca",
        "trigger_gallop_label": "Galope",
        "trigger_strong_click_label": "Clique forte",
        "trigger_engine_hum_label": "Ronco do motor",
        "preset_label": "Predefinição",
        "profile_label": "Perfil",
        "direct_audio_title": "Áudio direto",
        "mode_label": "Modo",
        "label_master_gain": "Volume geral da vibração",
        "slider_lo": "Limiar de acionamento (lo)",
        "slider_lo_hint": "Abaixo deste nível o motor permanece em silêncio.",
        "slider_hi": "Limiar de força máxima (hi)",
        "slider_hi_hint": "Neste nível ou acima — força máxima. Menor = mais sensível.",
        "slider_attack": "Ataque",
        "slider_attack_hint": "Com que rapidez o motor atinge sua força alvo.",
        "slider_release": "Decaimento",
        "slider_release_hint": "Com que rapidez o motor se apaga. Maior = resposta mais curta e brusca.",
        "slider_gamma": "Contraste (gama)",
        "slider_gamma_hint": "Acima de 1 — reage só a sons altos. Abaixo de 1 — mais sensível a sons baixos.",
        "slider_ceil_attack": "Supressão de fundo: velocidade",
        "slider_ceil_attack_hint": "Com que rapidez um fundo constante é suprimido. Menor = mais agressivo.",
        "slider_ceil_release": "Supressão de fundo: memória",
        "slider_ceil_release_hint": "Por quanto tempo o nível de fundo é lembrado entre picos.",
        "group_bass": "Graves (motor forte)",
        "group_treble": "Agudos (motor fraco)",
        "btn_dpad": "Direcional",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (pressionado)",
        "btn_l3": "L3 (analógico)",
        "btn_share": "Compartilhar / Criar",
        "btn_cross": "Cruz (✕)",
        "btn_circle": "Círculo (○)",
        "btn_triangle": "Triângulo (△)",
        "btn_square": "Quadrado (□)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (pressionado)",
        "btn_r3": "R3 (analógico)",
        "btn_options": "Options",
        "btn_ps": "PS",
        "group_left_side": "Lado esquerdo",
        "group_right_side": "Lado direito",
        "button_haptic_title": "Vibração dos botões",
        "button_haptic_hint": "Enquanto um botão é mantido pressionado, seu motor vibra continuamente — independentemente do som, somando-se à vibração de áudio normal. Botões do lado esquerdo vibram levemente o motor forte/esquerdo, os do lado direito o motor fraco/direito, cada um com sua própria intensidade.",
        "collapse_show": "Mostrar configurações",
        "collapse_hide": "Ocultar configurações",
        "game_profiles_enabled_checkbox": "Usar perfil do jogo",
    },
    "ko": {
        "home_vibration": "진동",
        "status_searching": "컨트롤러 검색 중…",
        "status_connected": "연결됨",
        "status_overridden": "Steam이 가로챔",
        "battery_unknown": "—",
        "btn_apply": "적용",
        "triggers_title": "어댑티브 트리거",
        "trigger_left_title": "왼쪽 트리거 (L2)",
        "trigger_right_title": "오른쪽 트리거 (R2)",
        "direct_audio_checkbox": "오디오를 모터로 직접 재생",
        "direct_audio_bt_checkbox": "블루투스로 활성화 (실험적)",
        "label_bt_chunk_ms": "오디오 청크 크기 (ms)",
        "led_visualizer_title": "몰입형 조명",
        "led_visualizer_checkbox": "몰입형 조명 활성화",
        "label_led_attack": "반응 속도",
        "label_led_release": "감쇠 속도",
        "label_led_gamma": "피크 대비",
        "label_led_bass_priority": "베이스 우선순위",
        "game_profiles_title": "게임 프로필",
        "label_direct_gain": "강도",
        "group_language": "언어",
        "trigger_custom_title": "커스텀 효과",
        "label_trigger_off": "꺼짐",
        "trig_mode_off": "꺼짐",
        "trig_mode_feedback": "저항",
        "trig_mode_weapon": "무기",
        "trig_mode_bow": "활",
        "trig_mode_machine": "머신건",
        "trig_mode_galloping": "갤럽",
        "trig_mode_vibration": "진동",
        "trig_mode_feedback_raw": "저항 (구간)",
        "trig_mode_vibration_raw": "진동 (구간)",
        "trig_param_position": "위치",
        "trig_param_strength": "강도",
        "trig_param_start": "시작",
        "trig_param_end": "끝",
        "trig_param_snap": "스냅",
        "trig_param_strength_a": "강도 A",
        "trig_param_strength_b": "강도 B",
        "trig_param_frequency": "주파수",
        "trig_param_period": "주기",
        "trig_param_first_foot": "첫 박자",
        "trig_param_second_foot": "두 번째 박자",
        "trig_param_amplitude": "진폭",
        "preset_balanced_label": "균형",
        "preset_cinema_label": "영화",
        "preset_music_label": "음악",
        "preset_voice_label": "음성 및 팟캐스트",
        "preset_max_label": "최대 민감도",
        "trigger_soft_label": "부드러운 저항",
        "trigger_hard_wall_label": "단단한 벽",
        "trigger_weapon_label": "웨폰 트리거",
        "trigger_bow_label": "활",
        "trigger_machine_label": "머신건",
        "trigger_clicker_label": "래칫",
        "trigger_gallop_label": "갤럽",
        "trigger_strong_click_label": "강한 클릭",
        "trigger_engine_hum_label": "엔진 웅웅거림",
        "preset_label": "프리셋",
        "profile_label": "프로필",
        "direct_audio_title": "다이렉트 오디오",
        "mode_label": "모드",
        "label_master_gain": "전체 진동 볼륨",
        "slider_lo": "작동 임계값 (lo)",
        "slider_lo_hint": "이 수준 이하에서는 모터가 작동하지 않습니다.",
        "slider_hi": "최대 강도 임계값 (hi)",
        "slider_hi_hint": "이 수준 이상에서 최대 강도가 됩니다. 값이 낮을수록 민감합니다.",
        "slider_attack": "어택",
        "slider_attack_hint": "모터가 목표 강도에 도달하는 속도입니다.",
        "slider_release": "릴리즈",
        "slider_release_hint": "모터가 잦아드는 속도입니다. 값이 클수록 반응이 더 짧고 날카롭습니다.",
        "slider_gamma": "대비 (감마)",
        "slider_gamma_hint": "1보다 크면 큰 소리에만 반응합니다. 1보다 작으면 작은 소리에도 민감해집니다.",
        "slider_ceil_attack": "배경 억제: 속도",
        "slider_ceil_attack_hint": "지속적인 배경음을 억제하는 속도입니다. 값이 낮을수록 더 공격적입니다.",
        "slider_ceil_release": "배경 억제: 기억 시간",
        "slider_ceil_release_hint": "피크 사이에 배경 수준을 기억하는 시간입니다.",
        "group_bass": "저음 (강한 모터)",
        "group_treble": "고음 (약한 모터)",
        "btn_dpad": "방향 패드",
        "btn_l1": "L1",
        "btn_l2_press": "L2 (누름)",
        "btn_l3": "L3 (스틱)",
        "btn_share": "공유 / 만들기",
        "btn_cross": "✕ (크로스)",
        "btn_circle": "○ (서클)",
        "btn_triangle": "△ (트라이앵글)",
        "btn_square": "□ (스퀘어)",
        "btn_r1": "R1",
        "btn_r2_press": "R2 (누름)",
        "btn_r3": "R3 (스틱)",
        "btn_options": "옵션",
        "btn_ps": "PS",
        "group_left_side": "왼쪽",
        "group_right_side": "오른쪽",
        "button_haptic_title": "버튼 진동",
        "button_haptic_hint": "버튼을 누르고 있는 동안 해당 모터가 소리와 무관하게 계속 진동하며, 일반 오디오 진동과 합쳐집니다. 왼쪽 버튼은 강한/왼쪽 모터를, 오른쪽 버튼은 약한/오른쪽 모터를 각각의 세기로 가볍게 진동시킵니다.",
        "collapse_show": "설정 표시",
        "collapse_hide": "설정 숨기기",
        "game_profiles_enabled_checkbox": "게임 프로필 사용",
    }
};
function t(lang, key) {
    return STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
}

// Mutable module-level cache, not React state: the Steam GameSessions hook
// below is registered once at plugin load (outside any component's
// lifecycle) and reads this on every app-launch event, so it needs to see
// whatever GameProfilesSection last wrote, not a stale closure snapshot.
let gameProfilesCache = {};
// Same reasoning as gameProfilesCache above - the app-lifetime handler
// registered in definePlugin() below needs to read this synchronously,
// outside React, so it can't just be component state.
let gameProfilesEnabledCache = true;
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
const getActiveRef = callable("get_active_ref");
const applyRef = callable("apply_ref");
const getGameProfiles = callable("get_game_profiles");
const setGameProfile = callable("set_game_profile");
const listTriggerPresets = callable("list_trigger_presets");
const getTriggerPreset = callable("get_trigger_preset");
const applyTriggerPreset = callable("apply_trigger_preset");
const turnOffTrigger = callable("turn_off_trigger");
const getCustomTrigger = callable("get_custom_trigger");
const applyCustomTrigger = callable("apply_custom_trigger");
const getDirectAudio = callable("get_direct_audio");
const setDirectAudioEnabled = callable("set_direct_audio_enabled");
const setDirectAudioBtEnabled = callable("set_direct_audio_bt_enabled");
const setBtChunkMs = callable("set_bt_chunk_ms");
const setDirectAudioGain = callable("set_direct_audio_gain");
const getGameProfilesEnabled = callable("get_game_profiles_enabled");
const setGameProfilesEnabled = callable("set_game_profiles_enabled");
const getBandSettings = callable("get_band_settings");
const setBandParam = callable("set_band_param");
const getButtonHaptics = callable("get_button_haptics");
const setButtonHaptic = callable("set_button_haptic");
const getLedVisualizer = callable("get_led_visualizer");
const setLedVisualizerEnabled = callable("set_led_visualizer_enabled");
const setLedAttack = callable("set_led_attack");
const setLedRelease = callable("set_led_release");
const setLedGamma = callable("set_led_gamma");
const setLedBassPriority = callable("set_led_bass_priority");
const getLanguage = callable("get_language");
const setLanguage = callable("set_language");
const PRESET_LABEL_KEYS = {
    balanced: "preset_balanced_label",
    cinema: "preset_cinema_label",
    music: "preset_music_label",
    voice: "preset_voice_label",
    max: "preset_max_label",
};
const TRIGGER_PRESET_LABEL_KEYS = {
    soft: "trigger_soft_label",
    hard_wall: "trigger_hard_wall_label",
    weapon: "trigger_weapon_label",
    bow: "trigger_bow_label",
    machine: "trigger_machine_label",
    clicker: "trigger_clicker_label",
    gallop: "trigger_gallop_label",
    strong_click: "trigger_strong_click_label",
    engine_hum: "trigger_engine_hum_label",
};
// Mirrors presets.TRIGGER_EFFECT_ORDER / TRIGGER_EFFECT_PARAMS in presets.py.
const TRIGGER_EFFECT_ORDER = [
    "off", "feedback", "weapon", "bow", "machine", "galloping", "vibration",
    "feedback_raw", "vibration_raw",
];
const TRIGGER_MODE_LABEL_KEYS = {
    off: "label_trigger_off",
    feedback: "trig_mode_feedback",
    weapon: "trig_mode_weapon",
    bow: "trig_mode_bow",
    machine: "trig_mode_machine",
    galloping: "trig_mode_galloping",
    vibration: "trig_mode_vibration",
    feedback_raw: "trig_mode_feedback_raw",
    vibration_raw: "trig_mode_vibration_raw",
};
// feedback_raw/vibration_raw are per-zone arrays (s0..s9 / a0..a9) rather
// than named fields - see the zone-label handling in TRIGGER_PARAM_LABEL_KEYS's
// caller below, which reuses trig_param_strength/trig_param_amplitude with
// the zone index appended instead of needing 20 more translation keys.
const TRIGGER_EFFECT_PARAMS = {
    off: [],
    feedback: [["position", 0, 9, 2], ["strength", 1, 8, 3]],
    weapon: [["start", 2, 7, 3], ["end", 3, 8, 6], ["strength", 1, 8, 6]],
    bow: [["start", 1, 8, 2], ["end", 2, 8, 7], ["strength", 1, 8, 6], ["snap", 1, 8, 8]],
    machine: [
        ["start", 1, 8, 2], ["end", 2, 9, 8], ["strength_a", 0, 7, 1],
        ["strength_b", 0, 7, 7], ["frequency", 1, 15, 4], ["period", 0, 15, 2],
    ],
    galloping: [
        ["start", 0, 8, 1], ["end", 1, 9, 8], ["first_foot", 0, 6, 3],
        ["second_foot", 1, 7, 5], ["frequency", 1, 15, 5],
    ],
    vibration: [["position", 0, 9, 1], ["amplitude", 1, 8, 6], ["frequency", 1, 15, 3]],
    feedback_raw: Array.from({ length: 10 }, (_, i) => [`s${i}`, 0, 8, 0]),
    vibration_raw: [
        ...Array.from({ length: 10 }, (_, i) => [`a${i}`, 0, 8, 0]),
        ["frequency", 1, 15, 5],
    ],
};
const TRIGGER_PARAM_LABEL_KEYS = {
    position: "trig_param_position", strength: "trig_param_strength",
    start: "trig_param_start", end: "trig_param_end", snap: "trig_param_snap",
    strength_a: "trig_param_strength_a", strength_b: "trig_param_strength_b",
    frequency: "trig_param_frequency", period: "trig_param_period",
    first_foot: "trig_param_first_foot", second_foot: "trig_param_second_foot",
    amplitude: "trig_param_amplitude",
};
// s0..s9 (feedback_raw) / a0..a9 (vibration_raw) -> "Strength 3" / "Amplitude 7".
function triggerParamLabel(key, t) {
    const m = /^([sa])(\d)$/.exec(key);
    if (m)
        return `${t(m[1] === "s" ? "trig_param_strength" : "trig_param_amplitude")} ${m[2]}`;
    return t(TRIGGER_PARAM_LABEL_KEYS[key] ?? key);
}
function defaultValues(mode) {
    const values = {};
    for (const [key, , , def] of TRIGGER_EFFECT_PARAMS[mode] ?? [])
        values[key] = def;
    return values;
}
function MainSection({ t }) {
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
        // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const statusLabel = status === "connected" ? t("status_connected")
        : status === "searching" ? t("status_searching")
            : status === "overridden" ? t("status_overridden")
                : status ?? "—";
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "DualSense Haptics", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("home_vibration"), checked: enabled, onChange: onToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.85em", opacity: 0.75 }, children: [SP_JSX.jsxs("span", { children: [statusLabel, " \u00B7 ", connectionLabel] }), SP_JSX.jsx("span", { children: battery !== null ? `${battery}%` : "" })] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("preset_label"), rgOptions: presetList.map((p) => ({ data: p, label: t(PRESET_LABEL_KEYS[p] ?? p) })), selectedOption: activePreset, onChange: onPresetChange }) }), profileList.length > 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("profile_label"), rgOptions: profileList.map((p) => ({ data: p, label: p })), selectedOption: activeProfile, onChange: onProfileChange }) })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_master_gain"), value: gain, min: 0.2, max: 2.5, step: 0.05, notchTicksVisible: false, onChange: onGainChange }) })] }));
}
function TriggerPresetRow({ side, label, t }) {
    const [options, setOptions] = SP_REACT.useState([]);
    const [selected, setSelected] = SP_REACT.useState("off");
    SP_REACT.useEffect(() => {
        (async () => {
            const list = await listTriggerPresets();
            setOptions(["off", ...list]);
            const active = await getTriggerPreset(side);
            setSelected(active ?? "off");
        })();
    }, [side]);
    const onChange = async (option) => {
        setSelected(option.data);
        if (option.data === "off")
            await turnOffTrigger(side);
        else
            await applyTriggerPreset(option.data, side);
    };
    return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: label, rgOptions: options.map((p) => ({
                data: p,
                label: p === "off" ? t("label_trigger_off") : t(TRIGGER_PRESET_LABEL_KEYS[p] ?? p),
            })), selectedOption: selected, onChange: onChange }) }));
}
function TriggersSection({ t }) {
    return (SP_JSX.jsxs(DFL.PanelSection, { title: t("triggers_title"), children: [SP_JSX.jsx(TriggerPresetRow, { side: "left", label: t("trigger_left_title"), t: t }), SP_JSX.jsx(TriggerPresetRow, { side: "right", label: t("trigger_right_title"), t: t })] }));
}
function CustomTriggerCard({ side, label, t }) {
    const [mode, setMode] = SP_REACT.useState("feedback");
    const [values, setValues] = SP_REACT.useState(defaultValues("feedback"));
    const [detailsOpen, setDetailsOpen] = SP_REACT.useState(false);
    SP_REACT.useEffect(() => {
        (async () => {
            const custom = await getCustomTrigger(side);
            if (custom && custom.mode) {
                setMode(custom.mode);
                setValues({ ...defaultValues(custom.mode), ...custom.values });
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [side]);
    const onModeChange = async (option) => {
        const newMode = option.data;
        const newValues = defaultValues(newMode);
        setMode(newMode);
        setValues(newValues);
        // Persist the mode switch to hardware+config right away (not just on
        // "Apply") - the gamescope QAM panel can remount this card mid-session
        // (e.g. returning focus from the dropdown's fullscreen flyout), and
        // without this the remount's getCustomTrigger() re-fetch would still see
        // the previously saved mode and snap the dropdown straight back to it.
        if (newMode === "off")
            await turnOffTrigger(side);
        else
            await applyCustomTrigger(newMode, newValues, side);
    };
    const onParamChange = (key, value) => {
        setValues((v) => ({ ...v, [key]: value }));
    };
    const onApply = async () => {
        if (mode === "off")
            await turnOffTrigger(side);
        else
            await applyCustomTrigger(mode, values, side);
    };
    return (SP_JSX.jsxs(DFL.PanelSection, { title: `${t("trigger_custom_title")} · ${label}`, children: [SP_JSX.jsx(CollapsibleToggle, { open: detailsOpen, onToggle: () => setDetailsOpen((o) => !o), t: t }), detailsOpen && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("mode_label"), rgOptions: TRIGGER_EFFECT_ORDER.map((m) => ({ data: m, label: t(TRIGGER_MODE_LABEL_KEYS[m] ?? m) })), selectedOption: mode, onChange: onModeChange }) }), mode !== "off" && (TRIGGER_EFFECT_PARAMS[mode] ?? []).length > 0 && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [(TRIGGER_EFFECT_PARAMS[mode] ?? []).map(([key, lo, hi]) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: triggerParamLabel(key, t), value: values[key] ?? lo, min: lo, max: hi, step: 1, notchTicksVisible: false, onChange: (v) => onParamChange(key, v) }) }, key))), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: onApply, children: t("btn_apply") }) })] }))] }))] }));
}
// Decky's @decky/ui has no built-in collapsible/accordion (checked its
// index.d.ts) - this hand-rolls one using ButtonItem (rather than a plain
// clickable <div>) so it stays reachable via the Deck's D-pad/focus-based
// navigation, not just a mouse/touch pointer.
function CollapsibleToggle({ open, onToggle, t }) {
    return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: onToggle, children: open ? `▼ ${t("collapse_hide")}` : `▶ ${t("collapse_show")}` }) }));
}
function CollapsibleSection({ title, t, children }) {
    const [open, setOpen] = SP_REACT.useState(false);
    return (SP_JSX.jsxs(DFL.PanelSection, { title: title, children: [SP_JSX.jsx(CollapsibleToggle, { open: open, onToggle: () => setOpen((o) => !o), t: t }), open && children] }));
}
function DirectAudioSection({ t }) {
    const [directAudio, setDirectAudioState] = SP_REACT.useState({
        enabled: true, gain: 5.0, bt_enabled: false, bt_chunk_ms: 20,
    });
    SP_REACT.useEffect(() => {
        (async () => {
            const fetched = await getDirectAudio();
            setDirectAudioState({ ...fetched, gain: snapToStep(fetched.gain, 1.0, 0.1) });
        })();
    }, []);
    const onUsbToggle = async (value) => {
        setDirectAudioState((d) => ({ ...d, enabled: value }));
        await setDirectAudioEnabled(value);
    };
    const onBtToggle = async (value) => {
        setDirectAudioState((d) => ({ ...d, bt_enabled: value }));
        await setDirectAudioBtEnabled(value);
    };
    const onChunkMsChange = async (option) => {
        setDirectAudioState((d) => ({ ...d, bt_chunk_ms: option.data }));
        await setBtChunkMs(option.data);
    };
    const onGainChange = async (value) => {
        setDirectAudioState((d) => ({ ...d, gain: value }));
        await setDirectAudioGain(value);
    };
    return (SP_JSX.jsxs(CollapsibleSection, { title: t("direct_audio_title"), t: t, children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: `USB — ${t("direct_audio_checkbox")}`, checked: directAudio.enabled, onChange: onUsbToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("direct_audio_bt_checkbox"), checked: directAudio.bt_enabled, onChange: onBtToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_direct_gain"), value: directAudio.gain, min: 1.0, max: 8.0, step: 0.1, notchTicksVisible: false, onChange: onGainChange }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("label_bt_chunk_ms"), rgOptions: BT_CHUNK_MS_CHOICES.map((v) => ({ data: v, label: `${v} ms` })), selectedOption: directAudio.bt_chunk_ms, onChange: onChunkMsChange }) })] }));
}
function LedVisualizerSection({ t }) {
    const [led, setLed] = SP_REACT.useState({ enabled: false, attack: 0.5, release: 0.08, gamma: 1.8, bass_priority: 0.6 });
    const [detailsOpen, setDetailsOpen] = SP_REACT.useState(false);
    SP_REACT.useEffect(() => {
        (async () => {
            const fetched = await getLedVisualizer();
            setLed({
                ...fetched,
                attack: snapToStep(fetched.attack, 0.05, 0.05),
                release: snapToStep(fetched.release, 0.0, 0.05),
                gamma: snapToStep(fetched.gamma, 0.5, 0.25),
                bass_priority: snapToStep(fetched.bass_priority, 0.0, 0.1),
            });
        })();
    }, []);
    const onToggle = async (value) => {
        setLed((l) => ({ ...l, enabled: value }));
        await setLedVisualizerEnabled(value);
    };
    const onAttackChange = async (value) => {
        setLed((l) => ({ ...l, attack: value }));
        await setLedAttack(value);
    };
    const onReleaseChange = async (value) => {
        setLed((l) => ({ ...l, release: value }));
        await setLedRelease(value);
    };
    const onGammaChange = async (value) => {
        setLed((l) => ({ ...l, gamma: value }));
        await setLedGamma(value);
    };
    const onBassPriorityChange = async (value) => {
        setLed((l) => ({ ...l, bass_priority: value }));
        await setLedBassPriority(value);
    };
    return (SP_JSX.jsxs(DFL.PanelSection, { title: t("led_visualizer_title"), children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("led_visualizer_checkbox"), checked: led.enabled, onChange: onToggle }) }), led.enabled && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(CollapsibleToggle, { open: detailsOpen, onToggle: () => setDetailsOpen((o) => !o), t: t }), detailsOpen && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_led_attack"), value: led.attack, min: 0.05, max: 1.0, step: 0.05, notchTicksVisible: false, onChange: onAttackChange }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_led_release"), value: led.release, min: 0.0, max: 0.5, step: 0.05, notchTicksVisible: false, onChange: onReleaseChange }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_led_gamma"), value: led.gamma, min: 0.5, max: 3.0, step: 0.25, notchTicksVisible: false, onChange: onGammaChange }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_led_bass_priority"), value: led.bass_priority, min: 0.0, max: 1.0, step: 0.1, notchTicksVisible: false, onChange: onBassPriorityChange }) })] }))] }))] }));
}
// Desktop's own slider is a continuous 1000-step control (see ui.py's
// ParamSlider), so values it saved can land anywhere in a range - not
// necessarily on one of Decky's SliderField fixed `step` positions (e.g.
// direct_audio.gain saved as 4.85 with this panel's step=0.1, which sits
// exactly between the 4.8/4.9 notches). Confirmed on real hardware that
// handing SliderField such an off-grid value makes its drag handle fail to
// render at all - snap to the nearest valid notch before ever setting state.
// Mirrors haptics_engine.py's BT_CHUNK_MS_CHOICES (10, BT_CHUNK_MS=20, 30) -
// a dropdown rather than a slider, both because a 3-way choice doesn't need
// fine-grained control and because SliderField couldn't render a handle for
// this particular value at all (see the git history on this file).
const BT_CHUNK_MS_CHOICES = [10, 20, 30];
function decimalsFor(step) {
    const s = step.toString();
    const i = s.indexOf(".");
    return i === -1 ? 0 : s.length - i - 1;
}
function snapToStep(value, min, step) {
    const snapped = min + Math.round((value - min) / step) * step;
    // The arithmetic above can leave binary-floating-point noise on values
    // that aren't exactly representable (0.08, 1.8, 0.6, ... - unlike 0.5,
    // which is) - e.g. 0.08000000000000002 instead of 0.08. Confirmed on real
    // hardware that SliderField's drag handle fails to render at all for such
    // a value, even though it's numerically "close enough" - clean it up to
    // the step's own decimal precision.
    return parseFloat(snapped.toFixed(decimalsFor(step)));
}
const BAND_LABEL_KEYS = {
    lo: "slider_lo", hi: "slider_hi", attack: "slider_attack", release: "slider_release",
    gamma: "slider_gamma", attack_s: "slider_ceil_attack", release_s: "slider_ceil_release",
};
// [min, max, step] - matches ui.py's ParamSlider construction for band_group() exactly.
const BAND_RANGES = {
    lo: [0.0, 0.05, 0.001],
    hi: [0.01, 0.3, 0.005],
    attack: [0.5, 0.99, 0.01],
    release: [0.1, 0.9, 0.01],
    gamma: [0.4, 2.5, 0.05],
    attack_s: [0.02, 0.5, 0.01],
    release_s: [0.3, 5.0, 0.1],
};
const BAND_KEYS = ["lo", "hi", "attack", "release", "gamma", "attack_s", "release_s"];
function BandSection({ band, title, t }) {
    const [settings, setSettings] = SP_REACT.useState({
        lo: 0.01, hi: 0.1, attack: 0.95, release: 0.5, gamma: 1.0, attack_s: 0.08, release_s: 2.5,
    });
    SP_REACT.useEffect(() => {
        (async () => {
            const fetched = await getBandSettings(band);
            const snapped = { ...fetched };
            for (const key of BAND_KEYS) {
                const [min, , step] = BAND_RANGES[key];
                snapped[key] = snapToStep(fetched[key], min, step);
            }
            setSettings(snapped);
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [band]);
    const onChange = (key) => async (value) => {
        setSettings((s) => ({ ...s, [key]: value }));
        await setBandParam(band, key, value);
    };
    return (SP_JSX.jsx(CollapsibleSection, { title: title, t: t, children: BAND_KEYS.map((key) => {
            const [min, max, step] = BAND_RANGES[key];
            return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t(BAND_LABEL_KEYS[key]), value: settings[key], min: min, max: max, step: step, notchTicksVisible: false, onChange: onChange(key) }) }, key));
        }) }));
}
// Real evdev button codes (confirmed via `python3 -c "from evdev import ecodes"`,
// matching ui.py's LEFT_BUTTON_OPTIONS/RIGHT_BUTTON_OPTIONS and
// haptics_engine.py's DPAD_VIRTUAL_CODE) - button_haptics config keys are
// str(code) on the Python side.
const LEFT_BUTTON_OPTIONS = [
    ["btn_dpad", -1],
    ["btn_l1", 310],
    ["btn_l2_press", 312],
    ["btn_l3", 317],
    ["btn_share", 314],
];
const RIGHT_BUTTON_OPTIONS = [
    ["btn_cross", 304],
    ["btn_circle", 305],
    ["btn_triangle", 307],
    ["btn_square", 308],
    ["btn_r1", 311],
    ["btn_r2_press", 313],
    ["btn_r3", 318],
    ["btn_options", 315],
    ["btn_ps", 316],
];
function ButtonHapticRow({ labelKey, code, t, entry, onChange }) {
    const onToggle = (value) => onChange(code, { ...entry, enabled: value });
    const onStrength = (value) => onChange(code, { ...entry, strength: value });
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t(labelKey), checked: entry.enabled, onChange: onToggle }) }), entry.enabled && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("trig_param_strength"), value: entry.strength, min: 0.0, max: 1.0, step: 0.05, notchTicksVisible: false, onChange: onStrength }) }))] }));
}
function ButtonHapticsSection({ t }) {
    const [entries, setEntries] = SP_REACT.useState({});
    SP_REACT.useEffect(() => {
        (async () => {
            const fetched = await getButtonHaptics();
            const snapped = {};
            for (const [code, entry] of Object.entries(fetched)) {
                snapped[code] = { ...entry, strength: snapToStep(entry.strength, 0.0, 0.05) };
            }
            setEntries(snapped);
        })();
    }, []);
    const entryFor = (code) => entries[String(code)] ?? { enabled: false, strength: 0.4 };
    const onRowChange = async (code, entry) => {
        setEntries((e) => ({ ...e, [String(code)]: entry }));
        await setButtonHaptic(String(code), entry.enabled, entry.strength);
    };
    const renderGroup = (options) => options.map(([labelKey, code]) => (SP_JSX.jsx(ButtonHapticRow, { labelKey: labelKey, code: code, t: t, entry: entryFor(code), onChange: onRowChange }, code)));
    return (SP_JSX.jsxs(CollapsibleSection, { title: t("button_haptic_title"), t: t, children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("span", { style: { fontSize: "0.85em", opacity: 0.75 }, children: t("group_left_side") }) }), renderGroup(LEFT_BUTTON_OPTIONS), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("span", { style: { fontSize: "0.85em", opacity: 0.75 }, children: t("group_right_side") }) }), renderGroup(RIGHT_BUTTON_OPTIONS)] }));
}
// Shared between the enable toggle below and the app-launch handler in
// definePlugin(): if this app already has a linked profile, switch to it;
// otherwise create one from whatever's currently active. Module-level (not
// inside a component) since the launch handler runs outside React entirely.
async function linkOrApplyGame(appid, name) {
    const entry = gameProfilesCache[appid];
    if (entry) {
        await applyRef(entry.ref);
    }
    else {
        const ref = await getActiveRef();
        await setGameProfile(appid, name, ref);
        gameProfilesCache = { ...gameProfilesCache, [appid]: { name, ref } };
    }
}
function GameProfilesSection({ t }) {
    const [runningApp, setRunningApp] = SP_REACT.useState(null);
    const [enabled, setEnabled] = SP_REACT.useState(true);
    SP_REACT.useEffect(() => {
        (async () => {
            gameProfilesCache = await getGameProfiles();
            gameProfilesEnabledCache = await getGameProfilesEnabled();
            setEnabled(gameProfilesEnabledCache);
        })();
        const interval = setInterval(() => {
            const app = DFL.Router.MainRunningApp;
            setRunningApp(app ? { appid: app.appid, name: app.display_name } : null);
        }, 2000);
        return () => clearInterval(interval);
    }, []);
    // Turning this on counts as a launch event for whatever game is running
    // right now: switches to its profile if it already has one, otherwise
    // links it to whatever's currently active (see linkOrApplyGame). From then
    // on, every actual game launch while this stays on does the same thing
    // automatically - see the RegisterForAppLifetimeNotifications handler in
    // definePlugin() below. Turning it off just stops intervening on launches;
    // whatever preset/profile is manually selected stays in effect.
    const onEnabledToggle = async (value) => {
        gameProfilesEnabledCache = value;
        setEnabled(value);
        await setGameProfilesEnabled(value);
        if (value && runningApp) {
            await linkOrApplyGame(runningApp.appid, runningApp.name);
        }
    };
    return (SP_JSX.jsx(DFL.PanelSection, { title: t("game_profiles_title"), children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("game_profiles_enabled_checkbox"), checked: enabled, onChange: onEnabledToggle }) }) }));
}
function SettingsSection({ lang, onLangChange, t }) {
    return (SP_JSX.jsx(DFL.PanelSection, { title: t("group_language"), children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("group_language"), rgOptions: LANGUAGES.map(([code, name]) => ({ data: code, label: name })), selectedOption: lang, onChange: (option) => onLangChange(option.data) }) }) }));
}
function Root() {
    const [lang, setLang] = SP_REACT.useState("en");
    SP_REACT.useEffect(() => {
        (async () => setLang(await getLanguage()))();
    }, []);
    const t$1 = (key) => t(lang, key);
    const onLangChange = async (code) => {
        setLang(code);
        await setLanguage(code);
    };
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(MainSection, { t: t$1 }), SP_JSX.jsx(GameProfilesSection, { t: t$1 }), SP_JSX.jsx(TriggersSection, { t: t$1 }), SP_JSX.jsx(CustomTriggerCard, { side: "left", label: t$1("trigger_left_title"), t: t$1 }), SP_JSX.jsx(CustomTriggerCard, { side: "right", label: t$1("trigger_right_title"), t: t$1 }), SP_JSX.jsx(DirectAudioSection, { t: t$1 }), SP_JSX.jsx(LedVisualizerSection, { t: t$1 }), SP_JSX.jsx(BandSection, { band: "bass", title: t$1("group_bass"), t: t$1 }), SP_JSX.jsx(BandSection, { band: "treble", title: t$1("group_treble"), t: t$1 }), SP_JSX.jsx(ButtonHapticsSection, { t: t$1 }), SP_JSX.jsx(SettingsSection, { lang: lang, onLangChange: onLangChange, t: t$1 })] }));
}
var index = definePlugin(() => {
    (async () => {
        gameProfilesCache = await getGameProfiles();
        gameProfilesEnabledCache = await getGameProfilesEnabled();
    })();
    // Registered once, outside any component's lifecycle, since a Steam game
    // can launch while the QAM panel (and GameProfilesSection) isn't even
    // mounted - reads gameProfilesCache (kept current by GameProfilesSection)
    // rather than a value captured at registration time. Same for
    // gameProfilesEnabledCache - the global on/off toggle for this whole
    // mechanism.
    const lifetimeReg = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((notification) => {
        if (!notification.bRunning || !gameProfilesEnabledCache)
            return;
        const appid = String(notification.unAppID);
        const name = DFL.Router.MainRunningApp?.display_name ?? appid;
        linkOrApplyGame(appid, name);
    });
    return {
        name: "DualSense Haptics",
        titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "DualSense Haptics" }),
        content: SP_JSX.jsx(Root, {}),
        icon: SP_JSX.jsx(FaGamepad, {}),
        onDismount() {
            lifetimeReg.unregister();
        },
    };
});

export { index as default };
//# sourceMappingURL=index.js.map
