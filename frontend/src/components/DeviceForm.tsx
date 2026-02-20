import { useState } from "react";
import { Device, DeviceCreate, createDevice, updateDevice } from "../api/client";
import { X } from "lucide-react";

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
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (key: keyof DeviceCreate, value: string | number) =>
    setForm((f) => ({ ...f, [key]: value }));

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

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">
            {device ? "Edit Device" : "Add Device"}
          </h2>
          <button onClick={onCancel} className="text-slate-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          {error && (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-2 text-sm">
              {error}
            </div>
          )}

          <Field label="Name">
            <input
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
                  required
                  value={form.hostname}
                  onChange={(e) => set("hostname", e.target.value)}
                  placeholder="192.168.1.1"
                />
              </Field>
            </div>
            <Field label="Port">
              <input
                required
                type="number"
                value={form.port}
                onChange={(e) => set("port", parseInt(e.target.value))}
              />
            </Field>
          </div>

          <Field label="Username">
            <input
              required
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
              placeholder="root"
            />
          </Field>

          <Field label="Auth Type">
            <select
              value={form.auth_type}
              onChange={(e) => set("auth_type", e.target.value)}
            >
              <option value="password">Password</option>
              <option value="key">SSH Key</option>
            </select>
          </Field>

          {form.auth_type === "password" ? (
            <Field label="Password">
              <input
                type="password"
                value={form.password ?? ""}
                onChange={(e) => set("password", e.target.value)}
                placeholder="••••••••"
              />
            </Field>
          ) : (
            <Field label="Private Key (PEM)">
              <textarea
                rows={5}
                value={form.private_key ?? ""}
                onChange={(e) => set("private_key", e.target.value)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                className="font-mono text-xs"
              />
            </Field>
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
      <div className="[&>input]:input [&>select]:input [&>textarea]:input">{children}</div>
    </div>
  );
}
