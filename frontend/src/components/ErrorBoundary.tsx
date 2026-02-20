import { Component } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";

interface Props { children: React.ReactNode; }
interface State { error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[CloudShell] Unhandled render error:", error, info);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-slate-900 border border-red-800/50 rounded-2xl p-8 text-center space-y-4">
          <AlertTriangle size={40} className="text-red-400 mx-auto" />
          <h2 className="text-lg font-semibold text-white">Something went wrong</h2>
          <p className="text-sm text-slate-400 font-mono bg-slate-800 rounded-lg px-4 py-3 text-left break-all">
            {error.message}
          </p>
          <button
            className="btn-primary flex items-center gap-2 mx-auto"
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={14} />
            Reload page
          </button>
        </div>
      </div>
    );
  }
}
