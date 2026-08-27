import {
  PanelSection,
  PanelSectionRow,
  ToggleField,
  SliderField,
  DropdownItem,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useState, useEffect } from "react";
import { FaGamepad } from "react-icons/fa";

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
}

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

const listTriggerPresets = callable<[], string[]>("list_trigger_presets");
const getTriggerPreset = callable<[side: string], string | null>("get_trigger_preset");
const applyTriggerPreset = callable<[preset_id: string, side: string], boolean>("apply_trigger_preset");
const turnOffTrigger = callable<[side: string], boolean>("turn_off_trigger");

const getDirectAudio = callable<[], DirectAudio>("get_direct_audio");
const setDirectAudioEnabled = callable<[value: boolean], boolean>("set_direct_audio_enabled");
const setDirectAudioBtEnabled = callable<[value: boolean], boolean>("set_direct_audio_bt_enabled");

const PRESET_LABELS: Record<string, string> = {
  balanced: "Balanced",
  cinema: "Cinema",
  music: "Music",
  voice: "Voice & Podcasts",
  max: "Maximum Sensitivity",
};

const TRIGGER_LABELS: Record<string, string> = {
  off: "Off",
  soft: "Soft Resistance",
  hard_wall: "Hard Wall",
  weapon: "Weapon Trigger",
  bow: "Bow",
  machine: "Machine Gun",
  clicker: "Clicker",
  gallop: "Gallop",
};

function TriggerRow({ side, label }: { side: "left" | "right"; label: string }) {
  const [options, setOptions] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("off");

  useEffect(() => {
    (async () => {
      const presets = await listTriggerPresets();
      setOptions(["off", ...presets]);
      const active = await getTriggerPreset(side);
      setSelected(active ?? "off");
    })();
  }, []);

  const onChange = async (option: { data: string }) => {
    setSelected(option.data);
    if (option.data === "off") await turnOffTrigger(side);
    else await applyTriggerPreset(option.data, side);
  };

  return (
    <PanelSectionRow>
      <DropdownItem
        label={label}
        rgOptions={options.map((p) => ({ data: p, label: TRIGGER_LABELS[p] ?? p }))}
        selectedOption={selected}
        onChange={onChange}
      />
    </PanelSectionRow>
  );
}

function Content() {
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

  const connectionLabel =
    connection === "usb" ? "USB" : connection === "bluetooth" ? "Bluetooth" : "—";
  const statusLabel =
    status === "connected" ? "Connected" : status === "searching" ? "Searching…" : status ?? "—";

  return (
    <PanelSection title="DualSense Haptics">
      <PanelSectionRow>
        <ToggleField label="Vibration" checked={enabled} onChange={onToggle} />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85em", opacity: 0.75 }}>
          <span>{statusLabel} &middot; {connectionLabel}</span>
          <span>{battery !== null ? `${battery}%` : ""}</span>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Preset"
          rgOptions={presetList.map((p) => ({ data: p, label: PRESET_LABELS[p] ?? p }))}
          selectedOption={activePreset}
          onChange={onPresetChange}
        />
      </PanelSectionRow>
      {profileList.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Profile"
            rgOptions={profileList.map((p) => ({ data: p, label: p }))}
            selectedOption={activeProfile}
            onChange={onProfileChange}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <SliderField
          label="Strength"
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

function TriggersSection() {
  return (
    <PanelSection title="Adaptive Triggers">
      <TriggerRow side="left" label="Left (L2)" />
      <TriggerRow side="right" label="Right (R2)" />
    </PanelSection>
  );
}

function DirectAudioSection() {
  const [directAudio, setDirectAudioState] = useState<DirectAudio>({
    enabled: true,
    gain: 5.0,
    bt_enabled: false,
  });

  useEffect(() => {
    (async () => setDirectAudioState(await getDirectAudio()))();
  }, []);

  const onUsbToggle = async (value: boolean) => {
    setDirectAudioState((d) => ({ ...d, enabled: value }));
    await setDirectAudioEnabled(value);
  };

  const onBtToggle = async (value: boolean) => {
    setDirectAudioState((d) => ({ ...d, bt_enabled: value }));
    await setDirectAudioBtEnabled(value);
  };

  return (
    <PanelSection title="Direct Audio">
      <PanelSectionRow>
        <ToggleField
          label="USB (literal audio on the motors)"
          checked={directAudio.enabled}
          onChange={onUsbToggle}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Bluetooth (experimental, needs SAxense)"
          checked={directAudio.bt_enabled}
          onChange={onBtToggle}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => {
  return {
    name: "DualSense Haptics",
    titleView: <div className={staticClasses.Title}>DualSense Haptics</div>,
    content: (
      <>
        <Content />
        <TriggersSection />
        <DirectAudioSection />
      </>
    ),
    icon: <FaGamepad />,
    onDismount() {},
  };
});
