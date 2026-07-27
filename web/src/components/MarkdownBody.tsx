/**
 * 对话消息 Markdown 渲染（助手回复 / 卡片说明）。
 * @author 赵振明
 * @date 2026-07-23 15:35:48
 */
"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  text: string;
  className?: string;
};

/**
 * 将 Markdown 文本渲染为安全 HTML 结构（默认不执行原始 HTML）。
 */
export function MarkdownBody({ text, className }: Props) {
  const src = text || "";
  if (!src.trim()) {
    return <div className={className || "md-body"} />;
  }
  return (
    <div className={className ? `${className} md-body` : "md-body"}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{src}</ReactMarkdown>
    </div>
  );
}
