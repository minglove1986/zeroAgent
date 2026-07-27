# 多轮技能 FC 设计

@author 赵振明
@date 2026-07-22 11:04:14

## 范围（已批准）

- `skill_fc_max_rounds` 默认 5
- 循环：tools → ask_user 出卡 / 无 tools 收尾 / 执行回灌继续
- 触顶强制结束 `path=skill_fc_max_rounds`
- Mock「多轮工具」：先 echo 再最终文本

## 不做

真 HTTP、Agent 层 FC、无限循环
