"use client";

/**
 * 管理端错误插画区（404/500）。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
import type { ReactNode } from "react";
import Link from "next/link";
import { Button, Space } from "antd";

export type ErrorHeroKind = "404" | "500";

const META: Record<ErrorHeroKind, { src: string; alt: string }> = {
  "404": { src: "/error/404.png", alt: "404 形象丢失" },
  "500": { src: "/error/500.png", alt: "服务器出错" },
};

/**
 * 居中展示错误插画与导航操作（不重复图内文案）。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
export function ErrorHero({
  kind,
  onRetry,
  extraAction,
}: {
  kind: ErrorHeroKind;
  onRetry?: () => void;
  /** 可选额外操作（如 global-error 的「返回登录」） */
  extraAction?: ReactNode;
}) {
  const meta = META[kind];
  return (
    <div
      style={{
        minHeight: "60vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        textAlign: "center",
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={meta.src}
        alt={meta.alt}
        style={{
          width: "min(520px, 100%)",
          height: "auto",
          objectFit: "contain",
          marginBottom: 20,
        }}
      />
      <Space wrap>
        {kind === "500" && onRetry ? (
          <Button type="primary" onClick={onRetry}>
            重试
          </Button>
        ) : null}
        <Link href="/overview">
          <Button type={kind === "404" ? "primary" : "default"}>返回概览</Button>
        </Link>
        {extraAction}
      </Space>
    </div>
  );
}
