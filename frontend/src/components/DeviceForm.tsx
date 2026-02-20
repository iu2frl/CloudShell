import { useRef, useState } from "react";
import { Device, DeviceCreate, createDevice, updateDevice } from "../api/client";
import { X, KeyRound, Copy, Check, Loader, Upload } from "lucide-react";

interface Props {
  device?: Device;
  onSave: (d: Device) => void;
  onCancel: () => void;
}

const EMPTY: DeviceCreate = {
  name: "",
  hostname: "",
  port: 22,
  username: "",
  auth_type: "password",
  password: "",
  private_key: "",
};

export function DeviceForm({ device, onSave, onCancel }: Props) {
  const [form, setForm] = useState<DeviceCreate>(
    device
      ? {
          name: device.name,
          hostname: device.hostname,
          port: device.port,
          username: device.username,
          auth_type: device.auth_type,
        }
      : { ...EMPTY }
  );
  const [error, setError]           = useState<string | null>(null);
  const [saving, setSaving]         = useState(false);
  const [generating, setGenerating] = useState(false);
  const [publicKey, setPublicKey]   = useState<string | null>(null);
  const [copied, setCopied]         = useState(false);
  const fileInputRef                = useRef<HTMLInputElement>(null);

  const set = (key: keyof DeviceCreate, value: string | number) =>
    setForm((f) => ({ ...f, [key]: value }));

  const loadKeyFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => set("private_key", reader.result as string);
    reader.readAsText(file);
    // Reset so the same file can be re-selected if needed
    e.target.value = "";
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = device
        ? await updateDevice(device.id, form)
        : await createDevice(form);
      onSave(saved);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const generateKeyPair = async () => {
    setGenerating(true);
    setError(null);
    try {
      const token = localStorage.getItem("token") ?? "";
      const res = await fetch("/api/keys/generate", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      set("private_key", data.private_key);
      setPublicKey(data.public_key);
    } catch (err) {
      setError(`Key generation failed: ${err}`);
    } finally {
      setGenerating(false);
    }
  };

  const copyPublicKey = () => {
    if (!publicKey) return;
    navigator.clipboard.writeText(publicKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
          <h2 className="text-lg font-semibold text-white">
            {device ? "Edit Device" : "Add Device"}
          </h2>
          <button onClick={onCancel} className="text-slate-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4 overflow-y-auto">
          {error && (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-2 text-sm">
              {error}
            </div>
          )}

          <Field label="Name">
            <input
              className="input"
              required
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="My Server"
            />
          </Field>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <Field label="Hostname / IP">
                <input
                  className="input"
                  required
                  value={form.hostname}
                  onChange={(e) => set("hostname", e.target.value)}
                  placeholder="192.168.1.1"
                />
              </Field>
            </div>
            <Field label="Port">
              <input
                className="input"
                required
                type="number"
                value={form.port}
                onChange={(e) => set("port", parseInt(e.target.value))}
              />
            </Field>
          </div>

          <Field label="Username">
            <input
              className="input"
              required
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
              placeholder="root"
            />
          </Field>

          <Field label="Auth Type">
            <select
              className="input"
              value={form.auth_type}
              onChange={(e) => {
                set("auth_type", e.target.value);
                setPublicKey(null);
              }}
            >
              <option value="password">Password</option>
              <option value="key">SSH Key</option>
            </select>
          </Field>

          {form.auth_type === "password" ? (
            <Field label="Password">
              <input
                className="input"
                type="password"
                value={form.password ?? ""}
                onChange={(e) => set("password", e.target.value)}
                placeholder="••••••••"
              />
            </Field>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                  Private Key (PEM)
                </label>
                <div className="flex items-center gap-3">
                  {/* Hidden file picker — triggered by the Upload button */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pem,.key,id_rsa,id_ed25519,id_ecdsa"
                    className="hidden"
                    onChange={loadKeyFile}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
                  >
                    <Upload size={12} />
                    Load file
                  </button>
                  <button
                    type="button"
                    onClick={generateKeyPair}
                    disabled={generating}
                    className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors disabled:opacity-50"
                  >
                    {generating
                      ? <Loader size={12} className="animate-spin" />
                      : <KeyRound size={12} />}
                    {generating ? "Generating…" : "Generate key pair"}
                  </button>
                </div>
              </div>
              <textarea
                rows={5}
                value={form.private_key ?? ""}
                onChange={(e) => set("private_key", e.target.value)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                className="input font-mono text-xs resize-none w-full"
              />

              {publicKey && (
                <div className="bg-green-900/20 border border-green-700/50 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-green-400">
                      Public key — add to <code className="text-green-300">~/.ssh/authorized_keys</code>
                    </span>
                    <button
                      type="button"
                      onClick={copyPublicKey}
                      className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300 transition-colors"
                    >
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                      {copied ? "Copied!" : "Copy"}
                    </button>
                  </div>
                  <pre className="text-[10px] text-green-300 break-all whitespace-pre-wrap font-mono leading-relaxed">
                    {publicKey}
                  </pre>
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onCancel} className="btn-ghost">
              Cancel
            </button>
            <button type="submit" disabled={saving} className="btn-primary">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
        {label}
      </label>
      {children}
    </div>
  );
}
