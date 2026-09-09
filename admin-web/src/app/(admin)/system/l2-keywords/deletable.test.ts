/**
 * L2 关键词可删判定单测。
 *
 * @author 赵振明
 * @date 2026-09-09 10:41:38
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isL2KeywordDeletable } from "./deletable";

describe("isL2KeywordDeletable", () => {
  it("allows system seed", () => {
    assert.equal(isL2KeywordDeletable("system"), true);
  });

  it("allows custom", () => {
    assert.equal(isL2KeywordDeletable("custom"), true);
  });

  it("allows missing origin", () => {
    assert.equal(isL2KeywordDeletable(undefined), true);
    assert.equal(isL2KeywordDeletable(null), true);
  });
});
