import { Sparkles } from 'lucide-react';

/**
 * 品牌标识：二次元立绘移除后的统一助手形象。
 *
 * 纯 CSS 几何标识（陶土橘圆角方块 + 星芒图标），随主题变量自动适配明暗；
 * 不依赖任何图片资源，避免再次出现"素材缺失 / 贴图缝隙"一类问题。
 * 配色口径对齐 Claude 桌面端品牌图标：陶土橘底 + 奶白星芒（浅色）/
 * 近黑星芒（深色，保证浅陶土上的对比度）；不做投影——平贴才干净。
 *
 * 尺寸档位：
 *  - sm：消息流助手头像（32px）
 *  - md：设置页「关于」应用图标（56px）
 *  - lg：安装引导页头部（88px）
 *  - xl：空态首页主形象（112px）
 */
interface Props {
  /** 尺寸档位，默认 sm */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** 追加样式类（如浮动动画 boot-float） */
  className?: string;
  /** 无障碍名称与悬浮提示 */
  title?: string;
}

const SIZE: Record<NonNullable<Props['size']>, { box: string; icon: number }> = {
  sm: { box: 'w-8 h-8 rounded-lg', icon: 15 },
  md: { box: 'w-14 h-14 rounded-xl', icon: 26 },
  lg: { box: 'w-[88px] h-[88px] rounded-2xl', icon: 40 },
  xl: { box: 'w-[112px] h-[112px] rounded-2xl', icon: 52 },
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
      className={`${s.box} flex-none flex items-center justify-center bg-tuan-accentSoft text-tuan-onAccent ${className}`}
    >
      <Sparkles size={s.icon} strokeWidth={1.8} />
    </span>
  );
}
