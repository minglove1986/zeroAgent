/**
 * L2 关键词是否允许软删（与后端 soft_delete_keyword 规则对齐）。
 *
 * @author 赵振明
 * @date 2026-09-09 10:41:38
 */

/**
 * 系统种子与自定义短语均可软删；系统种子可通过「恢复默认」找回。
 */
export function isL2KeywordDeletable(_origin?: string | null): boolean {
  return true;
}
