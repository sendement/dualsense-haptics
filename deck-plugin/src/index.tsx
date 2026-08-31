import {
  PanelSection,
  PanelSectionRow,
  ToggleField,
  SliderField,
  DropdownItem,
  ButtonItem,
  Router,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import { FaGamepad } from "react-icons/fa";
import { LANGUAGES, t as translate } from "./i18n";

interface Status {
  running: boolean;
  status: string | null;
  connection: string | null;
  battery_percent: number | null;
  battery_status: string | null;
}

interface DirectAudio {
  enabled: boolean;
  gain: number;
  bt_enabled: boolean;
  bt_chunk_ms: number;
}

interface BandSettings {
  lo: number;
  hi: number;
  attack: number;
  release: number;
  gamma: number;
  attack_s: number;
  release_s: number;
}

interface ButtonHapticEntry {
  enabled: boolean;
  strength: number;
}

interface LedVisualizer {
  enabled: boolean;
  attack: number;
  release: number;
  gamma: number;
  bass_priority: number;
}

interface CustomTrigger {
  mode: string;
  values: Record<string, number>;
}

interface GameProfileEntry {
  name: string;
  ref: string;
}

type GameProfiles = Record<string, GameProfileEntry>;

// Mutable module-level cache, not React state: the Steam GameSessions hook
// below is registered once at plugin load (outside any component's
// lifecycle) and reads this on every app-launch event, so it needs to see
// whatever GameProfilesSection last wrote, not a stale closure snapshot.
let gameProfilesCache: GameProfiles = {};
// Same reasoning as gameProfilesCache above - the app-lifetime handler
// registered in definePlugin() below needs to read this synchronously,
// outside React, so it can't just be component state.
let gameProfilesEnabledCache = true;

const startEngine = callable<[], boolean>("start_engine");
const stopEngine = callable<[], boolean>("stop_engine");
const isRunning = callable<[], boolean>("is_running");
const getStatus = callable<[], Status>("get_status");
const listPresets = callable<[], string[]>("list_presets");
const getActivePreset = callable<[], string | null>("get_active_preset");
const applyPreset = callable<[preset_id: string], boolean>("apply_preset");
const getGain = callable<[], number>("get_gain");
const setGain = callable<[value: number], boolean>("set_gain");

const listProfiles = callable<[], string[]>("list_profiles");
const getActiveProfile = callable<[], string | null>("get_active_profile");
const applyProfile = callable<[name: string], boolean>("apply_profile");

const getActiveRef = callable<[], string>("get_active_ref");
const applyRef = callable<[ref: string], boolean>("apply_ref");
const getGameProfiles = callable<[], GameProfiles>("get_game_profiles");
const setGameProfile = callable<[app_id: string, name: string, ref: string], boolean>("set_game_profile");

const listTriggerPresets = callable<[], string[]>("list_trigger_presets");
const getTriggerPreset = callable<[side: string], string | null>("get_trigger_preset");
const applyTriggerPreset = callable<[preset_id: string, side: string], boolean>("apply_trigger_preset");
const turnOffTrigger = callable<[side: string], boolean>("turn_off_trigger");
const getCustomTrigger = callable<[side: string], CustomTrigger | null>("get_custom_trigger");
const applyCustomTrigger = callable<[mode: string, values: Record<string, number>, side: string], boolean>(
  "apply_custom_trigger",
);

const getDirectAudio = callable<[], DirectAudio>("get_direct_audio");
const setDirectAudioEnabled = callable<[value: boolean], boolean>("set_direct_audio_enabled");
const setDirectAudioBtEnabled = callable<[value: boolean], boolean>("set_direct_audio_bt_enabled");
const setBtChunkMs = callable<[value: number], boolean>("set_bt_chunk_ms");
const setDirectAudioGain = callable<[value: number], boolean>("set_direct_audio_gain");

const getGameProfilesEnabled = callable<[], boolean>("get_game_profiles_enabled");
const setGameProfilesEnabled = callable<[value: boolean], boolean>("set_game_profiles_enabled");

const getBandSettings = callable<[band: string], BandSettings>("get_band_settings");
const setBandParam = callable<[band: string, key: string, value: number], boolean>("set_band_param");

const getButtonHaptics = callable<[], Record<string, ButtonHapticEntry>>("get_button_haptics");
const setButtonHaptic = callable<[code: string, enabled: boolean, strength: number], boolean>("set_button_haptic");

const getLedVisualizer = callable<[], LedVisualizer>("get_led_visualizer");
const setLedVisualizerEnabled = callable<[value: boolean], boolean>("set_led_visualizer_enabled");
const setLedAttack = callable<[value: number], boolean>("set_led_attack");
const setLedRelease = callable<[value: number], boolean>("set_led_release");
const setLedGamma = callable<[value: number], boolean>("set_led_gamma");
const setLedBassPriority = callable<[value: number], boolean>("set_led_bass_priority");

const getLanguage = callable<[], string>("get_language");
const setLanguage = callable<[code: string], boolean>("set_language");

const PRESET_LABEL_KEYS: Record<string, string> = {
  balanced: "preset_balanced_label",
  cinema: "preset_cinema_label",
  music: "preset_music_label",
  voice: "preset_voice_label",
  max: "preset_max_label",
};

const TRIGGER_PRESET_LABEL_KEYS: Record<string, string> = {
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
const TRIGGER_MODE_LABEL_KEYS: Record<string, string> = {
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
const TRIGGER_EFFECT_PARAMS: Record<string, [string, number, number, number][]> = {
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
  feedback_raw: Array.from({ length: 10 }, (_, i) => [`s${i}`, 0, 8, 0] as [string, number, number, number]),
  vibration_raw: [
    ...Array.from({ length: 10 }, (_, i) => [`a${i}`, 0, 8, 0] as [string, number, number, number]),
    ["frequency", 1, 15, 5] as [string, number, number, number],
  ],
};
const TRIGGER_PARAM_LABEL_KEYS: Record<string, string> = {
  position: "trig_param_position", strength: "trig_param_strength",
  start: "trig_param_start", end: "trig_param_end", snap: "trig_param_snap",
  strength_a: "trig_param_strength_a", strength_b: "trig_param_strength_b",
  frequency: "trig_param_frequency", period: "trig_param_period",
  first_foot: "trig_param_first_foot", second_foot: "trig_param_second_foot",
  amplitude: "trig_param_amplitude",
};

// s0..s9 (feedback_raw) / a0..a9 (vibration_raw) -> "Strength 3" / "Amplitude 7".
function triggerParamLabel(key: string, t: (key: string) => string): string {
  const m = /^([sa])(\d)$/.exec(key);
  if (m) return `${t(m[1] === "s" ? "trig_param_strength" : "trig_param_amplitude")} ${m[2]}`;
  return t(TRIGGER_PARAM_LABEL_KEYS[key] ?? key);
}

function defaultValues(mode: string): Record<string, number> {
  const values: Record<string, number> = {};
  for (const [key, , , def] of TRIGGER_EFFECT_PARAMS[mode] ?? []) values[key] = def;
  return values;
}

function MainSection({ t }: { t: (key: string) => string }) {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [connection, setConnection] = useState<string | null>(null);
  const [battery, setBattery] = useState<number | null>(null);
  const [presetList, setPresetList] = useState<string[]>([]);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [profileList, setProfileList] = useState<string[]>([]);
  const [activeProfile, setActiveProfile] = useState<string | null>(null);
  const [gain, setGainValue] = useState(1.0);

  useEffect(() => {
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

  const onToggle = async (value: boolean) => {
    setEnabled(value);
    if (value) await startEngine();
    else await stopEngine();
  };

  const onPresetChange = async (option: { data: string }) => {
    setActivePreset(option.data);
    setActiveProfile(null);
    await applyPreset(option.data);
  };

  const onProfileChange = async (option: { data: string }) => {
    setActiveProfile(option.data);
    setActivePreset(null);
    await applyProfile(option.data);
  };

  const onGainChange = async (value: number) => {
    setGainValue(value);
    await setGain(value);
  };

  const connectionLabel = connection === "usb" ? "USB" : connection === "bluetooth" ? "Bluetooth" : "—";
  const statusLabel =
    status === "connected" ? t("status_connected")
    : status === "searching" ? t("status_searching")
    : status === "overridden" ? t("status_overridden")
    : status ?? "—";

  return (
    <PanelSection title="DualSense Haptics">
      <PanelSectionRow>
        <ToggleField label={t("home_vibration")} checked={enabled} onChange={onToggle} />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85em", opacity: 0.75 }}>
          <span>{statusLabel} &middot; {connectionLabel}</span>
          <span>{battery !== null ? `${battery}%` : ""}</span>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t("preset_label")}
          rgOptions={presetList.map((p) => ({ data: p, label: t(PRESET_LABEL_KEYS[p] ?? p) }))}
          selectedOption={activePreset}
          onChange={onPresetChange}
        />
      </PanelSectionRow>
      {profileList.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label={t("profile_label")}
            rgOptions={profileList.map((p) => ({ data: p, label: p }))}
            selectedOption={activeProfile}
            onChange={onProfileChange}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <SliderField
          label={t("label_master_gain")}
          value={gain}
          min={0.2}
          max={2.5}
          step={0.05}
          notchTicksVisible={false}
          onChange={onGainChange}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

function TriggerPresetRow({ side, label, t }: { side: "left" | "right"; label: string; t: (key: string) => string }) {
  const [options, setOptions] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("off");

  useEffect(() => {
    (async () => {
      const list = await listTriggerPresets();
      setOptions(["off", ...list]);
      const active = await getTriggerPreset(side);
      setSelected(active ?? "off");
    })();
  }, [side]);

  const onChange = async (option: { data: string }) => {
    setSelected(option.data);
    if (option.data === "off") await turnOffTrigger(side);
    else await applyTriggerPreset(option.data, side);
  };

  return (
    <PanelSectionRow>
      <DropdownItem
        label={label}
        rgOptions={options.map((p) => ({
          data: p,
          label: p === "off" ? t("label_trigger_off") : t(TRIGGER_PRESET_LABEL_KEYS[p] ?? p),
        }))}
        selectedOption={selected}
        onChange={onChange}
      />
    </PanelSectionRow>
  );
}

function TriggersSection({ t }: { t: (key: string) => string }) {
  return (
    <PanelSection title={t("triggers_title")}>
      <TriggerPresetRow side="left" label={t("trigger_left_title")} t={t} />
      <TriggerPresetRow side="right" label={t("trigger_right_title")} t={t} />
    </PanelSection>
  );
}

function CustomTriggerCard({ side, label, t }: { side: "left" | "right"; label: string; t: (key: string) => string }) {
  const [mode, setMode] = useState<string>("feedback");
  const [values, setValues] = useState<Record<string, number>>(defaultValues("feedback"));
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    (async () => {
      const custom = await getCustomTrigger(side);
      if (custom && custom.mode) {
        setMode(custom.mode);
        setValues({ ...defaultValues(custom.mode), ...custom.values });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [side]);

  const onModeChange = async (option: { data: string }) => {
    const newMode = option.data;
    const newValues = defaultValues(newMode);
    setMode(newMode);
    setValues(newValues);
    // Persist the mode switch to hardware+config right away (not just on
    // "Apply") - the gamescope QAM panel can remount this card mid-session
    // (e.g. returning focus from the dropdown's fullscreen flyout), and
    // without this the remount's getCustomTrigger() re-fetch would still see
    // the previously saved mode and snap the dropdown straight back to it.
    if (newMode === "off") await turnOffTrigger(side);
    else await applyCustomTrigger(newMode, newValues, side);
  };

  const onParamChange = (key: string, value: number) => {
    setValues((v) => ({ ...v, [key]: value }));
  };

  const onApply = async () => {
    if (mode === "off") await turnOffTrigger(side);
    else await applyCustomTrigger(mode, values, side);
  };

  return (
    <PanelSection title={`${t("trigger_custom_title")} · ${label}`}>
      <CollapsibleToggle open={detailsOpen} onToggle={() => setDetailsOpen((o) => !o)} t={t} />
      {detailsOpen && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label={t("mode_label")}
              rgOptions={TRIGGER_EFFECT_ORDER.map((m) => ({ data: m, label: t(TRIGGER_MODE_LABEL_KEYS[m] ?? m) }))}
              selectedOption={mode}
              onChange={onModeChange}
            />
          </PanelSectionRow>
          {mode !== "off" && (TRIGGER_EFFECT_PARAMS[mode] ?? []).length > 0 && (
            <>
              {(TRIGGER_EFFECT_PARAMS[mode] ?? []).map(([key, lo, hi]) => (
                <PanelSectionRow key={key}>
                  <SliderField
                    label={triggerParamLabel(key, t)}
                    value={values[key] ?? lo}
                    min={lo}
                    max={hi}
                    step={1}
                    notchTicksVisible={false}
                    onChange={(v: number) => onParamChange(key, v)}
                  />
                </PanelSectionRow>
              ))}
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={onApply}>
                  {t("btn_apply")}
                </ButtonItem>
              </PanelSectionRow>
            </>
          )}
        </>
      )}
    </PanelSection>
  );
}

// Decky's @decky/ui has no built-in collapsible/accordion (checked its
// index.d.ts) - this hand-rolls one using ButtonItem (rather than a plain
// clickable <div>) so it stays reachable via the Deck's D-pad/focus-based
// navigation, not just a mouse/touch pointer.
function CollapsibleToggle({ open, onToggle, t }: { open: boolean; onToggle: () => void; t: (key: string) => string }) {
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={onToggle}>
        {open ? `▼ ${t("collapse_hide")}` : `▶ ${t("collapse_show")}`}
      </ButtonItem>
    </PanelSectionRow>
  );
}

function CollapsibleSection({ title, t, children }: { title: string; t: (key: string) => string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <PanelSection title={title}>
      <CollapsibleToggle open={open} onToggle={() => setOpen((o) => !o)} t={t} />
      {open && children}
    </PanelSection>
  );
}

function DirectAudioSection({ t }: { t: (key: string) => string }) {
  const [directAudio, setDirectAudioState] = useState<DirectAudio>({
    enabled: true, gain: 5.0, bt_enabled: false, bt_chunk_ms: 20,
  });

  useEffect(() => {
    (async () => {
      const fetched = await getDirectAudio();
      setDirectAudioState({ ...fetched, gain: snapToStep(fetched.gain, 1.0, 0.1) });
    })();
  }, []);

  const onUsbToggle = async (value: boolean) => {
    setDirectAudioState((d) => ({ ...d, enabled: value }));
    await setDirectAudioEnabled(value);
  };

  const onBtToggle = async (value: boolean) => {
    setDirectAudioState((d) => ({ ...d, bt_enabled: value }));
    await setDirectAudioBtEnabled(value);
  };

  const onChunkMsChange = async (option: { data: number }) => {
    setDirectAudioState((d) => ({ ...d, bt_chunk_ms: option.data }));
    await setBtChunkMs(option.data);
  };

  const onGainChange = async (value: number) => {
    setDirectAudioState((d) => ({ ...d, gain: value }));
    await setDirectAudioGain(value);
  };

  return (
    <CollapsibleSection title={t("direct_audio_title")} t={t}>
      <PanelSectionRow>
        <ToggleField label={`USB — ${t("direct_audio_checkbox")}`} checked={directAudio.enabled} onChange={onUsbToggle} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label={t("direct_audio_bt_checkbox")} checked={directAudio.bt_enabled} onChange={onBtToggle} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label={t("label_direct_gain")}
          value={directAudio.gain}
          min={1.0}
          max={8.0}
          step={0.1}
          notchTicksVisible={false}
          onChange={onGainChange}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t("label_bt_chunk_ms")}
          rgOptions={BT_CHUNK_MS_CHOICES.map((v) => ({ data: v, label: `${v} ms` }))}
          selectedOption={directAudio.bt_chunk_ms}
          onChange={onChunkMsChange}
        />
      </PanelSectionRow>
    </CollapsibleSection>
  );
}

function LedVisualizerSection({ t }: { t: (key: string) => string }) {
  const [led, setLed] = useState<LedVisualizer>({ enabled: false, attack: 0.5, release: 0.08, gamma: 1.8, bass_priority: 0.6 });
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
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

  const onToggle = async (value: boolean) => {
    setLed((l) => ({ ...l, enabled: value }));
    await setLedVisualizerEnabled(value);
  };

  const onAttackChange = async (value: number) => {
    setLed((l) => ({ ...l, attack: value }));
    await setLedAttack(value);
  };

  const onReleaseChange = async (value: number) => {
    setLed((l) => ({ ...l, release: value }));
    await setLedRelease(value);
  };

  const onGammaChange = async (value: number) => {
    setLed((l) => ({ ...l, gamma: value }));
    await setLedGamma(value);
  };

  const onBassPriorityChange = async (value: number) => {
    setLed((l) => ({ ...l, bass_priority: value }));
    await setLedBassPriority(value);
  };

  return (
    <PanelSection title={t("led_visualizer_title")}>
      <PanelSectionRow>
        <ToggleField label={t("led_visualizer_checkbox")} checked={led.enabled} onChange={onToggle} />
      </PanelSectionRow>
      {led.enabled && (
        <>
          <CollapsibleToggle open={detailsOpen} onToggle={() => setDetailsOpen((o) => !o)} t={t} />
          {detailsOpen && (
          <>
          <PanelSectionRow>
            <SliderField
              label={t("label_led_attack")}
              value={led.attack}
              min={0.05}
              max={1.0}
              step={0.05}
              notchTicksVisible={false}
              onChange={onAttackChange}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderField
              label={t("label_led_release")}
              value={led.release}
              min={0.0}
              max={0.5}
              step={0.05}
              notchTicksVisible={false}
              onChange={onReleaseChange}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderField
              label={t("label_led_gamma")}
              value={led.gamma}
              min={0.5}
              max={3.0}
              step={0.25}
              notchTicksVisible={false}
              onChange={onGammaChange}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderField
              label={t("label_led_bass_priority")}
              value={led.bass_priority}
              min={0.0}
              max={1.0}
              step={0.1}
              notchTicksVisible={false}
              onChange={onBassPriorityChange}
            />
          </PanelSectionRow>
          </>
          )}
        </>
      )}
    </PanelSection>
  );
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

function decimalsFor(step: number): number {
  const s = step.toString();
  const i = s.indexOf(".");
  return i === -1 ? 0 : s.length - i - 1;
}

function snapToStep(value: number, min: number, step: number): number {
  const snapped = min + Math.round((value - min) / step) * step;
  // The arithmetic above can leave binary-floating-point noise on values
  // that aren't exactly representable (0.08, 1.8, 0.6, ... - unlike 0.5,
  // which is) - e.g. 0.08000000000000002 instead of 0.08. Confirmed on real
  // hardware that SliderField's drag handle fails to render at all for such
  // a value, even though it's numerically "close enough" - clean it up to
  // the step's own decimal precision.
  return parseFloat(snapped.toFixed(decimalsFor(step)));
}

const BAND_LABEL_KEYS: Record<keyof BandSettings, string> = {
  lo: "slider_lo", hi: "slider_hi", attack: "slider_attack", release: "slider_release",
  gamma: "slider_gamma", attack_s: "slider_ceil_attack", release_s: "slider_ceil_release",
};
// [min, max, step] - matches ui.py's ParamSlider construction for band_group() exactly.
const BAND_RANGES: Record<keyof BandSettings, [number, number, number]> = {
  lo: [0.0, 0.05, 0.001],
  hi: [0.01, 0.3, 0.005],
  attack: [0.5, 0.99, 0.01],
  release: [0.1, 0.9, 0.01],
  gamma: [0.4, 2.5, 0.05],
  attack_s: [0.02, 0.5, 0.01],
  release_s: [0.3, 5.0, 0.1],
};
const BAND_KEYS: (keyof BandSettings)[] = ["lo", "hi", "attack", "release", "gamma", "attack_s", "release_s"];

function BandSection({ band, title, t }: { band: string; title: string; t: (key: string) => string }) {
  const [settings, setSettings] = useState<BandSettings>({
    lo: 0.01, hi: 0.1, attack: 0.95, release: 0.5, gamma: 1.0, attack_s: 0.08, release_s: 2.5,
  });

  useEffect(() => {
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

  const onChange = (key: keyof BandSettings) => async (value: number) => {
    setSettings((s) => ({ ...s, [key]: value }));
    await setBandParam(band, key, value);
  };

  return (
    <CollapsibleSection title={title} t={t}>
      {BAND_KEYS.map((key) => {
        const [min, max, step] = BAND_RANGES[key];
        return (
          <PanelSectionRow key={key}>
            <SliderField
              label={t(BAND_LABEL_KEYS[key])}
              value={settings[key]}
              min={min}
              max={max}
              step={step}
              notchTicksVisible={false}
              onChange={onChange(key)}
            />
          </PanelSectionRow>
        );
      })}
    </CollapsibleSection>
  );
}

// Real evdev button codes (confirmed via `python3 -c "from evdev import ecodes"`,
// matching ui.py's LEFT_BUTTON_OPTIONS/RIGHT_BUTTON_OPTIONS and
// haptics_engine.py's DPAD_VIRTUAL_CODE) - button_haptics config keys are
// str(code) on the Python side.
const LEFT_BUTTON_OPTIONS: [string, number][] = [
  ["btn_dpad", -1],
  ["btn_l1", 310],
  ["btn_l2_press", 312],
  ["btn_l3", 317],
  ["btn_share", 314],
];
const RIGHT_BUTTON_OPTIONS: [string, number][] = [
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

function ButtonHapticRow({ labelKey, code, t, entry, onChange }: {
  labelKey: string; code: number; t: (key: string) => string;
  entry: ButtonHapticEntry; onChange: (code: number, entry: ButtonHapticEntry) => void;
}) {
  const onToggle = (value: boolean) => onChange(code, { ...entry, enabled: value });
  const onStrength = (value: number) => onChange(code, { ...entry, strength: value });
  return (
    <>
      <PanelSectionRow>
        <ToggleField label={t(labelKey)} checked={entry.enabled} onChange={onToggle} />
      </PanelSectionRow>
      {entry.enabled && (
        <PanelSectionRow>
          <SliderField
            label={t("trig_param_strength")}
            value={entry.strength}
            min={0.0}
            max={1.0}
            step={0.05}
            notchTicksVisible={false}
            onChange={onStrength}
          />
        </PanelSectionRow>
      )}
    </>
  );
}

function ButtonHapticsSection({ t }: { t: (key: string) => string }) {
  const [entries, setEntries] = useState<Record<string, ButtonHapticEntry>>({});

  useEffect(() => {
    (async () => {
      const fetched = await getButtonHaptics();
      const snapped: Record<string, ButtonHapticEntry> = {};
      for (const [code, entry] of Object.entries(fetched)) {
        snapped[code] = { ...entry, strength: snapToStep(entry.strength, 0.0, 0.05) };
      }
      setEntries(snapped);
    })();
  }, []);

  const entryFor = (code: number): ButtonHapticEntry =>
    entries[String(code)] ?? { enabled: false, strength: 0.4 };

  const onRowChange = async (code: number, entry: ButtonHapticEntry) => {
    setEntries((e) => ({ ...e, [String(code)]: entry }));
    await setButtonHaptic(String(code), entry.enabled, entry.strength);
  };

  const renderGroup = (options: [string, number][]) =>
    options.map(([labelKey, code]) => (
      <ButtonHapticRow key={code} labelKey={labelKey} code={code} t={t} entry={entryFor(code)} onChange={onRowChange} />
    ));

  return (
    <CollapsibleSection title={t("button_haptic_title")} t={t}>
      <PanelSectionRow>
        <span style={{ fontSize: "0.85em", opacity: 0.75 }}>{t("group_left_side")}</span>
      </PanelSectionRow>
      {renderGroup(LEFT_BUTTON_OPTIONS)}
      <PanelSectionRow>
        <span style={{ fontSize: "0.85em", opacity: 0.75 }}>{t("group_right_side")}</span>
      </PanelSectionRow>
      {renderGroup(RIGHT_BUTTON_OPTIONS)}
    </CollapsibleSection>
  );
}

// Shared between the enable toggle below and the app-launch handler in
// definePlugin(): if this app already has a linked profile, switch to it;
// otherwise create one from whatever's currently active. Module-level (not
// inside a component) since the launch handler runs outside React entirely.
async function linkOrApplyGame(appid: string, name: string) {
  const entry = gameProfilesCache[appid];
  if (entry) {
    await applyRef(entry.ref);
  } else {
    const ref = await getActiveRef();
    await setGameProfile(appid, name, ref);
    gameProfilesCache = { ...gameProfilesCache, [appid]: { name, ref } };
  }
}

function GameProfilesSection({ t }: { t: (key: string) => string }) {
  const [runningApp, setRunningApp] = useState<{ appid: string; name: string } | null>(null);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    (async () => {
      gameProfilesCache = await getGameProfiles();
      gameProfilesEnabledCache = await getGameProfilesEnabled();
      setEnabled(gameProfilesEnabledCache);
    })();

    const interval = setInterval(() => {
      const app = Router.MainRunningApp;
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
  const onEnabledToggle = async (value: boolean) => {
    gameProfilesEnabledCache = value;
    setEnabled(value);
    await setGameProfilesEnabled(value);
    if (value && runningApp) {
      await linkOrApplyGame(runningApp.appid, runningApp.name);
    }
  };

  return (
    <PanelSection title={t("game_profiles_title")}>
      <PanelSectionRow>
        <ToggleField
          label={t("game_profiles_enabled_checkbox")}
          checked={enabled}
          onChange={onEnabledToggle}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

function SettingsSection({ lang, onLangChange, t }: { lang: string; onLangChange: (code: string) => void; t: (key: string) => string }) {
  return (
    <PanelSection title={t("group_language")}>
      <PanelSectionRow>
        <DropdownItem
          label={t("group_language")}
          rgOptions={LANGUAGES.map(([code, name]) => ({ data: code, label: name }))}
          selectedOption={lang}
          onChange={(option: { data: string }) => onLangChange(option.data)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

function Root() {
  const [lang, setLang] = useState("en");

  useEffect(() => {
    (async () => setLang(await getLanguage()))();
  }, []);

  const t = (key: string) => translate(lang, key);

  const onLangChange = async (code: string) => {
    setLang(code);
    await setLanguage(code);
  };

  return (
    <>
      <MainSection t={t} />
      <GameProfilesSection t={t} />
      <TriggersSection t={t} />
      <CustomTriggerCard side="left" label={t("trigger_left_title")} t={t} />
      <CustomTriggerCard side="right" label={t("trigger_right_title")} t={t} />
      <DirectAudioSection t={t} />
      <LedVisualizerSection t={t} />
      <BandSection band="bass" title={t("group_bass")} t={t} />
      <BandSection band="treble" title={t("group_treble")} t={t} />
      <ButtonHapticsSection t={t} />
      <SettingsSection lang={lang} onLangChange={onLangChange} t={t} />
    </>
  );
}

export default definePlugin(() => {
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
    if (!notification.bRunning || !gameProfilesEnabledCache) return;
    const appid = String(notification.unAppID);
    const name = Router.MainRunningApp?.display_name ?? appid;
    linkOrApplyGame(appid, name);
  });

  return {
    name: "DualSense Haptics",
    titleView: <div className={staticClasses.Title}>DualSense Haptics</div>,
    content: <Root />,
    icon: <FaGamepad />,
    onDismount() {
      lifetimeReg.unregister();
    },
  };
});
