/**
 * 品牌图标：引用 /public 下的 zeroagent-icon（普通 img，避免 next/image 水合问题）。
 *
 * @author 赵振明
 * @date 2026-07-29 16:34:00
 */
"use client";

type BrandMarkProps = {
  size?: number;
  className?: string;
  alt?: string;
  priority?: boolean;
};

/**
 * 按尺寸选择合适的品牌 PNG。
 */
function pickSrc(size: number): string {
  if (size <= 32) return "/zeroagent-icon-32.png";
  if (size <= 64) return "/zeroagent-icon-64.png";
  if (size <= 128) return "/zeroagent-icon-128.png";
  return "/zeroagent-icon-192.png";
}

/**
 * 渲染品牌 Z 图标（默认 32px）。
 */
export function BrandMark({
  size = 32,
  className,
  alt = "zeroAgent",
  priority = false,
}: BrandMarkProps) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- 静态品牌资源，避免 Image 优化链路影响登录页水合
    <img
      src={pickSrc(size)}
      alt={alt}
      width={size}
      height={size}
      className={className}
      decoding="async"
      loading={priority ? "eager" : "lazy"}
      style={{
        display: "block",
        width: size,
        height: size,
        borderRadius: Math.max(6, Math.round(size * 0.22)),
      }}
    />
  );
}
