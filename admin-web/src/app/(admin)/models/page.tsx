/**
 * 兼容旧菜单路径 /models → 实际页面 /system/llm-models。
 *
 * @author 赵振明
 * @date 2026-08-10 13:25:04
 */
import { redirect } from "next/navigation";

export default function ModelsRedirectPage() {
  redirect("/system/llm-models");
}
