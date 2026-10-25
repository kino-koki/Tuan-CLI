import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error, errorInfo: ErrorInfo): State {
    return { hasError: true, error, errorInfo };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: undefined, errorInfo: undefined });
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex-1 flex items-center justify-center p-8 bg-tuan-main">
          <div className="max-w-md w-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-[var(--tuan-danger-bg)] flex items-center justify-center mx-auto mb-4">
              <AlertTriangle size={32} className="text-[var(--tuan-danger)]" />
            </div>
            <h2 className="text-[18px] font-semibold text-tuan-text mb-2">
              页面出错了
            </h2>
            <p className="text-[13.5px] text-tuan-textSecondary mb-4 leading-relaxed">
              抱歉，应用遇到了意外错误。您可以尝试刷新页面或重新加载。
            </p>
            {this.state.error && (
              <div className="mb-4 p-3 bg-tuan-input border border-tuan-border rounded-xl text-left">
                <div className="text-[12px] text-tuan-textSecondary mb-1">错误信息：</div>
                <div className="text-[12.5px] text-tuan-text font-mono break-all">
                  {this.state.error.message}
                </div>
              </div>
            )}
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="cc-btn-ghost px-4 py-2 text-[13px] flex items-center gap-1.5"
              >
                <RefreshCw size={14} />
                重试
              </button>
              <button
                onClick={this.handleReload}
                className="cc-btn-primary px-4 py-2 text-[13px] flex items-center gap-1.5"
              >
                <RefreshCw size={14} />
                重新加载
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
