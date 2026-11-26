/**
 * 文档原始文件预览 Drawer：PDF/图片/文本页内预览；MD 源码+渲染；Office 仅下载。
 *
 * @author 赵振明
 * @date 2026-11-25 10:26:45
 */
"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Drawer,
  Segmented,
  Space,
  Spin,
  Typography,
} from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const { Text, Paragraph } = Typography;

export type PreviewKind =
  | "pdf"
  | "image"
  | "text"
  | "markdown"
  | "download"
  | "unsupported";

export type FilePreviewMeta = {
  title?: string;
  filename?: string;
  ext?: string;
  preview_kind?: PreviewKind;
};

type Props = {
  open: boolean;
  documentId: string;
  meta: FilePreviewMeta;
  onClose: () => void;
};

type MdMode = "render" | "source";

/**
 * 拉取鉴权文件字节；失败抛错。
 */
async function fetchDocumentFile(
  documentId: string,
  disposition?: "inline" | "attachment",
): Promise<Response> {
  const q = disposition ? `?disposition=${disposition}` : "";
  const res = await fetch(
    `/api/v1/documents/${encodeURIComponent(documentId)}/file${q}`,
    { credentials: "include" },
  );
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { message?: string };
      if (body?.message) msg = body.message;
    } catch {
      /* 非 JSON */
    }
    throw new Error(msg);
  }
  return res;
}

/**
 * 触发浏览器下载 blob。
 */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download.bin";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * 原始文件预览抽屉。
 */
export function OriginalFilePreview({
  open,
  documentId,
  meta,
  onClose,
}: Props) {
  const filename = meta.filename || meta.title || "原始文件";
  const kind: PreviewKind = meta.preview_kind || "unsupported";
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [textBody, setTextBody] = useState<string>("");
  const [mdMode, setMdMode] = useState<MdMode>("render");
  const [downloading, setDownloading] = useState(false);

  const revoke = useCallback((url: string | null) => {
    if (url) URL.revokeObjectURL(url);
  }, []);

  const loadPreview = useCallback(async () => {
    if (!open || !documentId) return;
    setLoading(true);
    setError(null);
    setTextBody("");
    setBlobUrl((prev) => {
      revoke(prev);
      return null;
    });

    if (kind === "download" || kind === "unsupported") {
      setLoading(false);
      return;
    }

    try {
      const res = await fetchDocumentFile(documentId, "inline");
      const blob = await res.blob();
      if (kind === "text" || kind === "markdown") {
        const buf = await blob.arrayBuffer();
        const decoded = new TextDecoder("utf-8", { fatal: false }).decode(buf);
        setTextBody(decoded);
      } else {
        const url = URL.createObjectURL(blob);
        setBlobUrl(url);
      }
    } catch (err) {
      setError((err as Error).message || "加载原始文件失败");
    } finally {
      setLoading(false);
    }
  }, [open, documentId, kind, revoke]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  useEffect(() => {
    if (open) return;
    setBlobUrl((prev) => {
      revoke(prev);
      return null;
    });
    setTextBody("");
    setError(null);
    setMdMode("render");
  }, [open, revoke]);

  /**
   * 强制 attachment 下载。
   */
  async function onDownload(): Promise<void> {
    setDownloading(true);
    try {
      const res = await fetchDocumentFile(documentId, "attachment");
      const blob = await res.blob();
      saveBlob(blob, filename);
    } catch (err) {
      setError((err as Error).message || "下载失败");
    } finally {
      setDownloading(false);
    }
  }

  let body: ReactNode = null;
  if (loading) {
    body = (
      <div style={{ textAlign: "center", padding: 48 }}>
        <Spin tip="加载原始文件…" />
      </div>
    );
  } else if (error) {
    body = (
      <Alert
        type="error"
        showIcon
        message="无法预览"
        description={error}
        action={
          <Button size="small" onClick={() => void loadPreview()}>
            重试
          </Button>
        }
      />
    );
  } else if (kind === "pdf" && blobUrl) {
    body = (
      <iframe
        title={filename}
        src={blobUrl}
        style={{
          width: "100%",
          height: "calc(100vh - 160px)",
          border: "none",
          background: "#525659",
        }}
      />
    );
  } else if (kind === "image" && blobUrl) {
    body = (
      <div style={{ textAlign: "center" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={blobUrl}
          alt={filename}
          style={{ maxWidth: "100%", maxHeight: "calc(100vh - 180px)" }}
        />
      </div>
    );
  } else if (kind === "text") {
    body = (
      <pre
        style={{
          margin: 0,
          padding: 12,
          background: "#fafafa",
          border: "1px solid #f0f0f0",
          borderRadius: 6,
          maxHeight: "calc(100vh - 180px)",
          overflow: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 13,
        }}
      >
        {textBody || "（空文件）"}
      </pre>
    );
  } else if (kind === "markdown") {
    body = (
      <div>
        <Segmented
          value={mdMode}
          onChange={(v) => setMdMode(v as MdMode)}
          options={[
            { label: "渲染", value: "render" },
            { label: "源码", value: "source" },
          ]}
          style={{ marginBottom: 12 }}
        />
        {mdMode === "source" ? (
          <pre
            style={{
              margin: 0,
              padding: 12,
              background: "#fafafa",
              border: "1px solid #f0f0f0",
              borderRadius: 6,
              maxHeight: "calc(100vh - 220px)",
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 13,
            }}
          >
            {textBody || "（空文件）"}
          </pre>
        ) : (
          <div
            style={{
              padding: 12,
              border: "1px solid #f0f0f0",
              borderRadius: 6,
              maxHeight: "calc(100vh - 220px)",
              overflow: "auto",
              background: "#fff",
            }}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {textBody || "*（空文件）*"}
            </ReactMarkdown>
          </div>
        )}
      </div>
    );
  } else {
    body = (
      <Alert
        type="info"
        showIcon
        message="该格式不支持页内预览"
        description={
          <Paragraph style={{ marginBottom: 8 }}>
            {kind === "download"
              ? "Word / Excel 等办公文档请下载后用本地软件打开。"
              : "未知或不受支持的文件类型，请下载后查看。"}
          </Paragraph>
        }
        action={
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={downloading}
            onClick={() => void onDownload()}
          >
            下载原文件
          </Button>
        }
      />
    );
  }

  return (
    <Drawer
      title={
        <Space direction="vertical" size={0}>
          <Text strong>原始文件预览</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {filename}
            {meta.ext ? ` · ${meta.ext}` : ""}
          </Text>
        </Space>
      }
      open={open}
      onClose={onClose}
      width={840}
      destroyOnClose
      extra={
        <Button
          icon={<DownloadOutlined />}
          loading={downloading}
          onClick={() => void onDownload()}
        >
          下载
        </Button>
      }
    >
      {body}
    </Drawer>
  );
}
