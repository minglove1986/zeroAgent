# Prompt 变量插值 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 模板 `{{var}}` 插值 + schema 校验 + 版本回滚

**Architecture:** interpolate 纯函数 → load 时合并上下文 → publish 快照 → rollback 恢复 draft

**Tech Stack:** FastAPI、Alembic 0014、pytest、Next.js

### Task 1: 迁移与模型
### Task 2: 插值/校验/加载
### Task 3: API（模板/Agent）+ runtime
### Task 4: 前端 + 测试 + CHECKPOINT
