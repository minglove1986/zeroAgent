/**
 * 首页入口 → 登录。
 * @author 赵振明
 * @date 2026-07-21 16:50:00
 */
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/login");
}
