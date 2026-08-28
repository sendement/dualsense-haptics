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
        "battery_unknown": "—",
        "btn_apply": "Apply",
        "triggers_title": "Adaptive Triggers",
        "trigger_left_title": "Left Trigger (L2)",
        "trigger_right_title": "Right Trigger (R2)",
        "direct_audio_checkbox": "Play audio straight through the motors",
        "direct_audio_bt_checkbox": "Enable over Bluetooth (experimental)",
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
        "mode_label": "Mode"
    },
    "ru": {
        "home_vibration": "Вибрация",
        "status_searching": "Поиск контроллера...",
        "status_connected": "Подключено",
        "battery_unknown": "—",
        "btn_apply": "Применить",
        "triggers_title": "Адаптивные триггеры",
        "trigger_left_title": "Левый триггер (L2)",
        "trigger_right_title": "Правый триггер (R2)",
        "direct_audio_checkbox": "Играть звук напрямую через моторы",
        "direct_audio_bt_checkbox": "Включить по Bluetooth (экспериментально)",
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
        "mode_label": "Режим"
    },
    "zh": {
        "home_vibration": "振动",
        "status_searching": "正在搜索控制器…",
        "status_connected": "已连接",
        "battery_unknown": "—",
        "btn_apply": "应用",
        "triggers_title": "自适应扳机",
        "trigger_left_title": "左扳机 (L2)",
        "trigger_right_title": "右扳机 (R2)",
        "direct_audio_checkbox": "直接通过马达播放音频",
        "direct_audio_bt_checkbox": "通过蓝牙启用（实验性）",
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
        "mode_label": "模式"
    },
    "es": {
        "home_vibration": "Vibración",
        "status_searching": "Buscando mando…",
        "status_connected": "Conectado",
        "battery_unknown": "—",
        "btn_apply": "Aplicar",
        "triggers_title": "Gatillos adaptativos",
        "trigger_left_title": "Gatillo izquierdo (L2)",
        "trigger_right_title": "Gatillo derecho (R2)",
        "direct_audio_checkbox": "Reproducir audio directamente en los motores",
        "direct_audio_bt_checkbox": "Activar por Bluetooth (experimental)",
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
        "mode_label": "Modo"
    },
    "de": {
        "home_vibration": "Vibration",
        "status_searching": "Suche nach Controller…",
        "status_connected": "Verbunden",
        "battery_unknown": "—",
        "btn_apply": "Anwenden",
        "triggers_title": "Adaptive Trigger",
        "trigger_left_title": "Linker Trigger (L2)",
        "trigger_right_title": "Rechter Trigger (R2)",
        "direct_audio_checkbox": "Audio direkt über die Motoren abspielen",
        "direct_audio_bt_checkbox": "Über Bluetooth aktivieren (experimentell)",
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
        "mode_label": "Modus"
    },
    "fr": {
        "home_vibration": "Vibration",
        "status_searching": "Recherche de la manette…",
        "status_connected": "Connectée",
        "battery_unknown": "—",
        "btn_apply": "Appliquer",
        "triggers_title": "Gâchettes adaptatives",
        "trigger_left_title": "Gâchette gauche (L2)",
        "trigger_right_title": "Gâchette droite (R2)",
        "direct_audio_checkbox": "Jouer l'audio directement sur les moteurs",
        "direct_audio_bt_checkbox": "Activer par Bluetooth (expérimental)",
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
        "mode_label": "Mode"
    },
    "ja": {
        "home_vibration": "振動",
        "status_searching": "コントローラーを検索中…",
        "status_connected": "接続済み",
        "battery_unknown": "—",
        "btn_apply": "適用",
        "triggers_title": "アダプティブトリガー",
        "trigger_left_title": "左トリガー (L2)",
        "trigger_right_title": "右トリガー (R2)",
        "direct_audio_checkbox": "音声をモーターに直接再生する",
        "direct_audio_bt_checkbox": "Bluetoothで有効にする（実験的機能）",
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
        "mode_label": "モード"
    },
    "pt": {
        "home_vibration": "Vibração",
        "status_searching": "Procurando controle…",
        "status_connected": "Conectado",
        "battery_unknown": "—",
        "btn_apply": "Aplicar",
        "triggers_title": "Gatilhos adaptativos",
        "trigger_left_title": "Gatilho esquerdo (L2)",
        "trigger_right_title": "Gatilho direito (R2)",
        "direct_audio_checkbox": "Reproduzir áudio diretamente nos motores",
        "direct_audio_bt_checkbox": "Ativar via Bluetooth (experimental)",
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
        "mode_label": "Modo"
    },
    "ko": {
        "home_vibration": "진동",
        "status_searching": "컨트롤러 검색 중…",
        "status_connected": "연결됨",
        "battery_unknown": "—",
        "btn_apply": "적용",
        "triggers_title": "어댑티브 트리거",
        "trigger_left_title": "왼쪽 트리거 (L2)",
        "trigger_right_title": "오른쪽 트리거 (R2)",
        "direct_audio_checkbox": "오디오를 모터로 직접 재생",
        "direct_audio_bt_checkbox": "블루투스로 활성화 (실험적)",
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
        "mode_label": "모드"
    }
};
function t(lang, key) {
    return STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
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
const getCustomTrigger = callable("get_custom_trigger");
const applyCustomTrigger = callable("apply_custom_trigger");
const getDirectAudio = callable("get_direct_audio");
const setDirectAudioEnabled = callable("set_direct_audio_enabled");
const setDirectAudioBtEnabled = callable("set_direct_audio_bt_enabled");
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
    const statusLabel = status === "connected" ? t("status_connected") : status === "searching" ? t("status_searching") : status ?? "—";
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "DualSense Haptics", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("home_vibration"), checked: enabled, onChange: onToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.85em", opacity: 0.75 }, children: [SP_JSX.jsxs("span", { children: [statusLabel, " \u00B7 ", connectionLabel] }), SP_JSX.jsx("span", { children: battery !== null ? `${battery}%` : "" })] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("preset_label"), rgOptions: presetList.map((p) => ({ data: p, label: t(PRESET_LABEL_KEYS[p] ?? p) })), selectedOption: activePreset, onChange: onPresetChange }) }), profileList.length > 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("profile_label"), rgOptions: profileList.map((p) => ({ data: p, label: p })), selectedOption: activeProfile, onChange: onProfileChange }) })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: t("label_direct_gain"), value: gain, min: 0.2, max: 2.5, step: 0.05, notchTicksVisible: false, onChange: onGainChange }) })] }));
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
    return (SP_JSX.jsxs(DFL.PanelSection, { title: `${t("trigger_custom_title")} · ${label}`, children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: t("mode_label"), rgOptions: TRIGGER_EFFECT_ORDER.map((m) => ({ data: m, label: t(TRIGGER_MODE_LABEL_KEYS[m] ?? m) })), selectedOption: mode, onChange: onModeChange }) }), (TRIGGER_EFFECT_PARAMS[mode] ?? []).map(([key, lo, hi]) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.SliderField, { label: triggerParamLabel(key, t), value: values[key] ?? lo, min: lo, max: hi, step: 1, notchTicksVisible: false, onChange: (v) => onParamChange(key, v) }) }, key))), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: onApply, children: t("btn_apply") }) })] }));
}
function DirectAudioSection({ t }) {
    const [directAudio, setDirectAudioState] = SP_REACT.useState({ enabled: true, gain: 5.0, bt_enabled: false });
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
    return (SP_JSX.jsxs(DFL.PanelSection, { title: t("direct_audio_title"), children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: `USB — ${t("direct_audio_checkbox")}`, checked: directAudio.enabled, onChange: onUsbToggle }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: t("direct_audio_bt_checkbox"), checked: directAudio.bt_enabled, onChange: onBtToggle }) })] }));
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
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(MainSection, { t: t$1 }), SP_JSX.jsx(TriggersSection, { t: t$1 }), SP_JSX.jsx(CustomTriggerCard, { side: "left", label: t$1("trigger_left_title"), t: t$1 }), SP_JSX.jsx(CustomTriggerCard, { side: "right", label: t$1("trigger_right_title"), t: t$1 }), SP_JSX.jsx(DirectAudioSection, { t: t$1 }), SP_JSX.jsx(SettingsSection, { lang: lang, onLangChange: onLangChange, t: t$1 })] }));
}
var index = definePlugin(() => {
    return {
        name: "DualSense Haptics",
        titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "DualSense Haptics" }),
        content: SP_JSX.jsx(Root, {}),
        icon: SP_JSX.jsx(FaGamepad, {}),
        onDismount() { },
    };
});

export { index as default };
//# sourceMappingURL=index.js.map
