import Spinner from './Spinner';

/**
 * 品牌标识：二次元立绘移除后的统一助手形象。
 *
 * 纯 CSS 菊花动画（Claude Code 官方菊花：8 片实心花瓣，符号来自
 * claude-daisy-assets/ 的 claude-daisy-symbol.svg，Wikimedia Commons CC0），
 * 不背方块、不做投影——菊花直接以品牌暖橙（--tuan-accent）浮在背景上，
 * 浅米/深炭两种主题下都与背景同色系、融为一体，随主题变量自动适配明暗。
 * 不依赖任何图片资源，避免再次出现"素材缺失 / 贴图缝隙"一类问题。
 *
 * 尺寸档位：
 *  - sm：消息流助手头像（菊花 22px）
 *  - md：设置页「关于」应用图标（菊花 30px）
 *  - lg：安装引导页头部（菊花 44px）
 *  - xl：空态首页主形象（菊花 58px）
 */
interface Props {
  /** 尺寸档位，默认 sm */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** 追加样式类（如浮动动画 boot-float） */
  className?: string;
  /** 无障碍名称与悬浮提示 */
  title?: string;
}

const SIZE: Record<NonNullable<Props['size']>, { box: string; spin: string }> = {
  sm: { box: '', spin: 'cc-spinner-22' },
  md: { box: '', spin: 'cc-spinner-30' },
  lg: { box: '', spin: 'cc-spinner-44' },
  xl: { box: '', spin: 'cc-spinner-58' },
};

export default function BrandMark({
  size = 'sm',
  className = '',
  title = '青小团',
}: Props) {
  const s = SIZE[size];
  return (
    <span
      title={title}
      aria-label={title}
      className={`flex-none inline-flex items-center justify-center text-tuan-accent ${s.box} ${className}`}
    >
      <Spinner className={s.spin} />
    </span>
  );
}
