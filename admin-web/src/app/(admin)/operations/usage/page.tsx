"use client";

/**
 * 用量成本：LiteLLM 按模型汇总（详细以 LiteLLM 为准）。
 *
 * @author 赵振明
 * @date 2026-08-12 09:36:20
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Card,
  Collapse,
  DatePicker,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type SpendRow = {
  model_name: string;
  display_name: string;
  enabled: boolean;
  matched: boolean;
  spend: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  api_requests: number;
};

type SpendPayload = {
  start_date: string;
  end_date: string;
  source: string;
  litellm_ui_url: string;
  disclaimer: string;
  totals: {
    spend: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    api_requests: number;
  };
  items: SpendRow[];
  unmatched: SpendRow[];
};

const DEFAULT_RANGE: [Dayjs, Dayjs] = [dayjs().subtract(6, "day"), dayjs()];

export default function UsagePage() {
  const { message } = App.useApp();
  const [range, setRange] = useState<[Dayjs, Dayjs]>(DEFAULT_RANGE);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SpendPayload | null>(null);

  useAdminPageTitle("用量成本");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const start = range[0].format("YYYY-MM-DD");
      const end = range[1].format("YYYY-MM-DD");
      const res = await apiJson<SpendPayload>(
        `/api/v1/admin/litellm/spend/by-model?start_date=${start}&end_date=${end}`,
      );
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载用量失败");
        setData(null);
        return;
      }
      setData(res.data);
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [range, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<SpendRow> = useMemo(
    () => [
      {
        title: "显示名",
        dataIndex: "display_name",
        width: 160,
      },
      {
        title: "model_name",
        dataIndex: "model_name",
        width: 180,
        render: (v: string) => (
          <span style={{ fontFamily: "monospace", fontSize: 12 }}>{v}</span>
        ),
      },
      {
        title: "启用",
        dataIndex: "enabled",
        width: 80,
        render: (v: boolean) =>
          v ? <Tag color="green">是</Tag> : <Tag>否</Tag>,
      },
      {
        title: "请求数",
        dataIndex: "api_requests",
        width: 90,
      },
      {
        title: "prompt tokens",
        dataIndex: "prompt_tokens",
        width: 120,
      },
      {
        title: "completion tokens",
        dataIndex: "completion_tokens",
        width: 140,
      },
      {
        title: "total tokens",
        dataIndex: "total_tokens",
        width: 120,
      },
      {
        title: "spend (USD)",
        dataIndex: "spend",
        width: 120,
        render: (v: number) => (Number.isFinite(v) ? v.toFixed(6) : "—"),
      },
    ],
    [],
  );

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={
          data?.disclaimer ||
          "详细用量与计费以 LiteLLM 系统为准；本页仅为汇总展示。"
        }
        description={
          <span>
            数据源：LiteLLM
            {data?.litellm_ui_url ? (
              <>
                {" · "}
                <a
                  href={data.litellm_ui_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  打开 LiteLLM 控制台
                </a>
              </>
            ) : null}
          </span>
        }
      />

      <Card
        title="按模型汇总"
        extra={
          <DatePicker.RangePicker
            value={range}
            allowClear={false}
            onChange={(v) => {
              if (v && v[0] && v[1]) {
                setRange([v[0], v[1]]);
              }
            }}
          />
        }
      >
        {data?.totals ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            合计：请求 {data.totals.api_requests} · tokens{" "}
            {data.totals.total_tokens} · spend{" "}
            {Number(data.totals.spend).toFixed(6)} USD（
            {data.start_date} ~ {data.end_date}）
          </Typography.Paragraph>
        ) : null}
        <Table
          rowKey="model_name"
          loading={loading}
          columns={columns}
          dataSource={data?.items || []}
          pagination={{ pageSize: 20 }}
          scroll={{ x: 1100 }}
          size="middle"
        />
        {(data?.unmatched?.length || 0) > 0 ? (
          <Collapse
            style={{ marginTop: 16 }}
            items={[
              {
                key: "unmatched",
                label: `目录外模型用量（${data?.unmatched.length}）`,
                children: (
                  <Table
                    rowKey="model_name"
                    size="small"
                    columns={columns}
                    dataSource={data?.unmatched || []}
                    pagination={false}
                    scroll={{ x: 1100 }}
                  />
                ),
              },
            ]}
          />
        ) : null}
      </Card>
    </Space>
  );
}
