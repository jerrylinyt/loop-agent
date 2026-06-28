"""
tree.py — 拆解＝驗證同構樹的狀態表示與持久化。

樹是 opt-in：不存在 TREE.md 時 tree_enabled() 回 False，
Chunk 2+ 的 plan_loop / loop 走原平 phase 邏輯，既有行為零變動。

持久化用既有單行 k:v 風格（與 CONTROL.md / PLAN.md 同機制），
引擎用 state.get_val / state.set_val 讀寫，不把整棵樹塞進 LLM context。
"""

import os
import re
import logging
from state import get_val, set_val

logger = logging.getLogger(__name__)

# ─────────────── 節點狀態常數 ───────────────
PENDING = "PENDING"
DECOMPOSED = "DECOMPOSED"
LEAF = "LEAF"
IN_PROGRESS = "IN_PROGRESS"
CONVERGED = "CONVERGED"
NEEDS_REVISION = "NEEDS_REVISION"
FROZEN = "FROZEN"

ALL_STATES = (PENDING, DECOMPOSED, LEAF, IN_PROGRESS, CONVERGED, NEEDS_REVISION, FROZEN)

# 每個節點落盤的欄位（前綴 node_{id}_）
_NODE_FIELDS = ("state", "children", "parent", "depth", "stable_rounds", "reflow_count", "depends_on")


# ─────────────── 路徑與啟用判定 ───────────────

def tree_md_path(cfg: dict) -> str:
    return os.path.join(os.path.dirname(cfg["control"]) or ".", "TREE.md")


def tree_enabled(cfg: dict) -> bool:
    path = tree_md_path(cfg)
    if not os.path.exists(path):
        return False
    return get_val(path, "tree_enabled") == "true"


# ─────────────── seed ───────────────

_TREE_HEADER = """\
# 🌱 TREE — 拆解＝驗證同構樹狀態（引擎專用，不入 LLM context）

> 持久化格式：單行 k:v，與 CONTROL.md 同機制。
> 引擎用 state.get_val / set_val 讀寫個別欄位。

```yaml
tree_enabled: true
tree_root: {root}
tree_total_nodes: 1
tree_total_leaves: 0
tree_max_depth: 0
```

"""

_NODE_BLOCK = """\
```yaml
# ── 節點：{node_id} ──
node_{node_id}_state: {state}
node_{node_id}_children:
node_{node_id}_parent: {parent}
node_{node_id}_depth: {depth}
node_{node_id}_depends_on: {depends_on}
node_{node_id}_stable_rounds: 0
node_{node_id}_reflow_count: 0
```
"""


def seed_tree(path: str, root_id: str = "root") -> bool:
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(_TREE_HEADER.format(root=root_id))
            f.write(_NODE_BLOCK.format(node_id=root_id, state=PENDING, parent="", depth="0", depends_on=""))
        return True
    except OSError as e:
        logger.error(f"Failed to seed TREE: {e}")
        return False


# ─────────────── 節點讀取 ───────────────

def _node_key(node_id: str, field: str) -> str:
    return f"node_{node_id}_{field}"


def get_node(path: str, node_id: str) -> dict | None:
    if not os.path.exists(path):
        return None
    state = get_val(path, _node_key(node_id, "state"))
    if state is None:
        return None
    result = {}
    for field in _NODE_FIELDS:
        result[field] = get_val(path, _node_key(node_id, field)) or ""
    # children 轉 list
    raw = result["children"]
    result["children"] = [c.strip() for c in raw.split(",") if c.strip()] if raw else []
    # depends_on 轉 list（同層兄弟 ID）
    raw_dep = result["depends_on"]
    result["depends_on"] = [d.strip() for d in raw_dep.split(",") if d.strip()] if raw_dep else []
    # depth 轉 int
    try:
        result["depth"] = int(result["depth"])
    except (ValueError, TypeError):
        result["depth"] = 0
    # stable_rounds / reflow_count 轉 int
    for k in ("stable_rounds", "reflow_count"):
        try:
            result[k] = int(result[k])
        except (ValueError, TypeError):
            result[k] = 0
    return result


def set_node_field(path: str, node_id: str, field: str, value: str):
    set_val(path, _node_key(node_id, field), value)


# ─────────────── 子節點操作 ───────────────

def _append_block(path: str, text: str):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + text)
    except OSError as e:
        logger.error(f"Failed to append to {path}: {e}")


def _update_global_counts(path: str):
    """重新計算全局計數（total_nodes, total_leaves, max_depth）。"""
    nodes, leaves, max_d = 0, 0, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return
    for m in re.finditer(r"^\s*node_(\S+?)_state\s*:\s*(\S+)", content, re.MULTILINE):
        nodes += 1
        if m.group(2) == LEAF:
            leaves += 1
    for m in re.finditer(r"^\s*node_\S+?_depth\s*:\s*(\d+)", content, re.MULTILINE):
        d = int(m.group(1))
        if d > max_d:
            max_d = d
    set_val(path, "tree_total_nodes", str(nodes))
    set_val(path, "tree_total_leaves", str(leaves))
    set_val(path, "tree_max_depth", str(max_d))


def add_child(path: str, parent_id: str, child_id: str,
              initial_state: str = PENDING, depends_on: str = "") -> bool:
    parent = get_node(path, parent_id)
    if parent is None:
        logger.error(f"Parent node '{parent_id}' not found")
        return False
    if get_node(path, child_id) is not None:
        logger.warning(f"Child node '{child_id}' already exists")
        return False

    parent_depth = parent["depth"]
    child_depth = parent_depth + 1

    # 寫入子節點 k:v block（depends_on=同層兄弟 ID，供執行期依賴排序）
    _append_block(path, _NODE_BLOCK.format(
        node_id=child_id, state=initial_state,
        parent=parent_id, depth=str(child_depth), depends_on=depends_on))

    # 更新父的 children 清單
    children = parent["children"]
    children.append(child_id)
    set_node_field(path, parent_id, "children", ",".join(children))

    # 父有子就是 DECOMPOSED（如果還是 PENDING 的話）
    if parent["state"] == PENDING:
        set_node_field(path, parent_id, "state", DECOMPOSED)

    _update_global_counts(path)
    return True


def remove_node(path: str, node_id: str) -> bool:
    """移除一個節點及其所有子孫。供人類 gate fail-path 的局部重拆用。"""
    node = get_node(path, node_id)
    if node is None:
        return False

    # 先遞迴移除所有子孫
    for child_id in node["children"]:
        remove_node(path, child_id)

    # 從父的 children 清單移除自己
    parent_id = node.get("parent") if isinstance(node.get("parent"), str) else ""
    if parent_id:
        parent = get_node(path, parent_id)
        if parent:
            new_children = [c for c in parent["children"] if c != node_id]
            set_node_field(path, parent_id, "children", ",".join(new_children))

    # 移除該節點的所有 k:v 行
    prefix = f"node_{node_id}_"
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 也移除節點的註解標題行
        comment_marker = f"# ── 節點：{node_id} ──"
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(prefix.replace("_", "_", 1)):
                # 匹配 node_{id}_* 的 k:v 行
                if re.match(rf"^\s*node_{re.escape(node_id)}_\w+\s*:", line):
                    continue
            if comment_marker in stripped:
                continue
            out.append(line)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(out)
    except OSError as e:
        logger.error(f"Failed to remove node {node_id}: {e}")
        return False

    _update_global_counts(path)
    return True


# ─────────────── 查詢 ───────────────

def _iter_node_ids(path: str):
    """yield 所有節點 ID。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*node_(\S+?)_state\s*:", line)
                if m:
                    yield m.group(1)
    except OSError:
        return


def list_leaves(path: str) -> list[str]:
    return [nid for nid in _iter_node_ids(path)
            if get_val(path, _node_key(nid, "state")) in (LEAF, IN_PROGRESS)]


def list_by_state(path: str, state: str) -> list[str]:
    return [nid for nid in _iter_node_ids(path)
            if get_val(path, _node_key(nid, "state")) == state]


def all_children_converged(path: str, node_id: str) -> bool:
    node = get_node(path, node_id)
    if node is None:
        return False
    children = node["children"]
    if not children:
        return node["state"] == CONVERGED
    return all(
        get_val(path, _node_key(cid, "state")) == CONVERGED
        for cid in children
    )


def next_pending_node(path: str) -> str | None:
    """DFS 順序找第一個 PENDING 節點（規劃期每 cycle 拆一個）。"""
    if not os.path.exists(path):
        return None
    root = get_val(path, "tree_root")
    if not root:
        return None
    return _dfs_find_pending(path, root)


def _dfs_find_pending(path: str, node_id: str) -> str | None:
    node = get_node(path, node_id)
    if node is None:
        return None
    if node["state"] == PENDING:
        return node_id
    for child in node["children"]:
        result = _dfs_find_pending(path, child)
        if result:
            return result
    return None


def tree_planning_complete(path: str) -> bool:
    """無 PENDING 節點 = 樹級規劃完成。"""
    if not os.path.exists(path):
        return False
    return len(list_by_state(path, PENDING)) == 0


# ─────────────── 執行期查詢 ───────────────

def _deps_satisfied(path: str, node_id: str) -> bool:
    """node 的所有 depends_on 是否都已 CONVERGED。

    - 自我依賴：忽略。
    - 未知/不存在的依賴 ID：視為已滿足（不製造死結；參照正確性由拆解 gate 把關）。
    """
    node = get_node(path, node_id)
    if node is None:
        return True
    for dep in node.get("depends_on", []):
        if dep == node_id:
            continue
        dep_state = get_val(path, _node_key(dep, "state"))
        if dep_state is None:
            continue  # 未知依賴 → 不阻擋
        if dep_state != CONVERGED:
            return False
    return True


def next_ready_leaf(path: str) -> str | None:
    """找下一個可執行的葉子（LEAF 或 NEEDS_REVISION 狀態），且其依賴的兄弟都已 CONVERGED。

    依賴排序：葉子的 depends_on（拆解時宣告，如各變體 depends_on base）未全部 CONVERGED 前不排程，
    使「base 先於變體」之類的整合順序自動成立，避免對著還沒成形的介面先做、合併時邏輯衝突。
    若所有未完成葉子都被未收斂的依賴卡住（含循環依賴），會回傳 None → loop 端 fail-safe 停下交人。
    """
    if not os.path.exists(path):
        return None
    for nid in _iter_node_ids(path):
        st = get_val(path, _node_key(nid, "state"))
        if st not in (LEAF, NEEDS_REVISION):
            continue
        if _deps_satisfied(path, nid):
            return nid
    return None


def try_unlock_parent(path: str, node_id: str) -> str | None:
    """葉子 CONVERGED 後：檢查父節點是否所有子都 CONVERGED。

    是 → 回傳父 ID（供整合驗證）；否 → None。
    遞迴往上：若父也解鎖，繼續檢查祖父。
    """
    node = get_node(path, node_id)
    if node is None:
        return None
    parent_id = node.get("parent") if isinstance(node.get("parent"), str) else ""
    if not parent_id:
        return None
    if all_children_converged(path, parent_id):
        return parent_id
    return None


def mark_leaf_needs_revision(path: str, node_id: str) -> bool:
    """整合驗證失敗 → 回流 (a)：退回葉子，重開修改項迴圈。"""
    node = get_node(path, node_id)
    if node is None:
        return False
    reflow = node["reflow_count"] + 1
    set_node_field(path, node_id, "state", NEEDS_REVISION)
    set_node_field(path, node_id, "stable_rounds", "0")
    set_node_field(path, node_id, "reflow_count", str(reflow))
    return True


# ─────────────── decomp 工單（每節點一份，供 agent 填寫拆解結果） ───────────────

def decomp_dir(cfg: dict) -> str:
    return os.path.join(os.path.dirname(cfg["control"]) or ".", "tree")


def decomp_file_path(cfg: dict, node_id: str) -> str:
    return os.path.join(decomp_dir(cfg), f"{node_id}.decomp.md")


_DECOMP_SEED = """\
# 🌱 拆解工單：{node_id}

> 由引擎建立。agent 每輪獨立重推 proposed_children，引擎追蹤集合穩定收斂。
> ⚠️ 集合穩定 ≠ 正確：穩定只代表連續 N 輪提出相同子項，正確性由人類 gate 承接。

```yaml
node_id: {node_id}
parent: {parent}
description: {description}

integration_contract:
proposed_children:
decomp_gate_last:
decomp_changed_last:
```
"""


def seed_decomp_file(cfg: dict, node_id: str, description: str = "") -> str:
    """建立 decomp 工單。回傳路徑。已存在則跳過。"""
    ddir = decomp_dir(cfg)
    os.makedirs(ddir, exist_ok=True)
    fpath = decomp_file_path(cfg, node_id)
    if os.path.exists(fpath):
        return fpath
    tree_path = tree_md_path(cfg)
    node = get_node(tree_path, node_id)
    parent = node["parent"] if node else ""
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(_DECOMP_SEED.format(
                node_id=node_id, parent=parent,
                description=description or node_id))
    except OSError as e:
        logger.error(f"Failed to seed decomp file for {node_id}: {e}")
    return fpath


def read_proposed_children(decomp_path: str) -> str:
    """讀 proposed_children 原始值（逗號分隔字串），用於跨輪比對。"""
    return get_val(decomp_path, "proposed_children") or ""


def finalize_node_children(tree_path: str, cfg: dict, node_id: str) -> list[str]:
    """節點拆解收斂後：讀 decomp 工單 → 在 TREE.md 建子節點。回傳新建的子 ID 清單。"""
    decomp_path = decomp_file_path(cfg, node_id)
    raw = read_proposed_children(decomp_path)
    if not raw:
        return []

    child_ids = [c.strip() for c in raw.split(",") if c.strip()]
    created = []
    for cid in child_ids:
        child_type = get_val(decomp_path, f"child_{cid}_type") or "leaf"
        initial_state = LEAF if child_type == "leaf" else PENDING
        dep = get_val(decomp_path, f"child_{cid}_depends_on") or ""
        if add_child(tree_path, node_id, cid, initial_state, depends_on=dep):
            created.append(cid)
    return created


def reset_subtree_for_replan(tree_path: str, node_id: str) -> bool:
    """人類 gate fail-path：局部重拆。

    移除 node_id 的所有子孫 → node_id 狀態改回 PENDING → stable_rounds 歸零。
    其餘節點不動。回傳 True 表示成功。
    """
    node = get_node(tree_path, node_id)
    if node is None:
        logger.error(f"Node '{node_id}' not found for replan")
        return False
    # 移除所有子孫
    for child_id in list(node["children"]):
        remove_node(tree_path, child_id)
    # 重設自身
    set_node_field(tree_path, node_id, "state", PENDING)
    set_node_field(tree_path, node_id, "children", "")
    set_node_field(tree_path, node_id, "stable_rounds", "0")
    _update_global_counts(tree_path)
    return True


def format_tree_for_human(tree_path: str) -> str:
    """產生人類可讀的整棵樹摘要，用於 gated 停點呈現。"""
    summary = tree_summary(tree_path)
    if not summary:
        return "(無樹)"

    lines = [
        f"節點總數: {summary['total_nodes']}  葉子: {summary['total_leaves']}  "
        f"最大深度: {summary['max_depth']}",
        f"狀態分布: {', '.join(f'{s}={c}' for s, c in summary['state_counts'].items() if c > 0)}",
        "",
    ]

    root_id = get_val(tree_path, "tree_root") or "root"
    _format_subtree(tree_path, root_id, lines, indent=0)
    return "\n".join(lines)


def _format_subtree(tree_path: str, node_id: str, lines: list, indent: int):
    node = get_node(tree_path, node_id)
    if node is None:
        return
    prefix = "  " * indent
    marker = "🍃" if node["state"] in (LEAF, IN_PROGRESS) else "📦"
    lines.append(f"{prefix}{marker} {node_id} [{node['state']}]")
    for child_id in node["children"]:
        _format_subtree(tree_path, child_id, lines, indent + 1)


def check_leaf_min_unit(decomp_path: str, cfg: dict) -> list[str]:
    """檢查 decomp 工單中 type=leaf 的子項是否符合 min_unit proxy。

    有 child_{id}_files / child_{id}_lines 數字才比；沒有不誤報。
    回傳違規子項 ID 清單（空 = 全過或無數字可比）。
    """
    raw = read_proposed_children(decomp_path)
    if not raw:
        return []

    mu = cfg.get("min_unit", {})
    max_files = mu.get("max_files", 3)
    max_lines = mu.get("max_lines", 150)

    violations = []
    for cid in (c.strip() for c in raw.split(",") if c.strip()):
        ctype = get_val(decomp_path, f"child_{cid}_type") or ""
        if ctype != "leaf":
            continue
        files_str = get_val(decomp_path, f"child_{cid}_files")
        lines_str = get_val(decomp_path, f"child_{cid}_lines")
        exceeded = False
        if files_str:
            try:
                if int(files_str) > max_files:
                    exceeded = True
            except ValueError:
                pass
        if lines_str:
            try:
                if int(lines_str) > max_lines:
                    exceeded = True
            except ValueError:
                pass
        if exceeded:
            violations.append(cid)
    return violations


# ─────────────── 硬 BREAKER 查詢（Chunk 7） ───────────────
# 撞線即凍結交人類，程式不准升級/重試/自我放寬。

def check_depth_breaker(path: str, max_depth: int) -> list[str]:
    """檢查樹中是否有任何節點深度 ≥ max_depth。

    回傳超標的 node_id 清單（空 = 安全）。
    """
    if not os.path.exists(path):
        return []
    violations = []
    for nid in _iter_node_ids(path):
        depth_str = get_val(path, _node_key(nid, "depth"))
        try:
            if int(depth_str or "0") >= max_depth:
                violations.append(nid)
        except (ValueError, TypeError):
            pass
    return violations


def check_leaves_breaker(path: str, max_leaves: int) -> tuple[int, bool]:
    """檢查葉子總數是否超過 max_leaves。

    計算 LEAF + IN_PROGRESS 狀態的節點數。
    max_leaves 是「明顯壞掉才觸發的跳閘」，不是把樹壓小的調校目標。
    回傳 (count, exceeded)。
    """
    if not os.path.exists(path):
        return (0, False)
    count = 0
    for nid in _iter_node_ids(path):
        st = get_val(path, _node_key(nid, "state"))
        if st in (LEAF, IN_PROGRESS):
            count += 1
    return (count, count > max_leaves)


def tree_summary(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    state_counts = {s: 0 for s in ALL_STATES}
    nodes = []
    for nid in _iter_node_ids(path):
        nodes.append(nid)
        st = get_val(path, _node_key(nid, "state")) or ""
        if st in state_counts:
            state_counts[st] += 1

    total_nodes = get_val(path, "tree_total_nodes") or str(len(nodes))
    total_leaves = get_val(path, "tree_total_leaves") or "0"
    max_depth = get_val(path, "tree_max_depth") or "0"

    return {
        "total_nodes": int(total_nodes),
        "total_leaves": int(total_leaves),
        "max_depth": int(max_depth),
        "state_counts": state_counts,
        "node_ids": nodes,
    }
