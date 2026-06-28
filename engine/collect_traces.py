#!/usr/bin/env python3
import os
import sys
import json
import argparse
import logging
from datetime import datetime

# Add current directory to path to load config/utils if needed
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("collect_traces")

def as_int(v, d=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d

def parse_index_file(index_path: str) -> list[dict]:
    workspaces = []
    if not os.path.exists(index_path):
        logger.warning(f"Index file not found: {index_path}")
        return workspaces

    try:
        header_seen = False
        with open(index_path, "r", encoding="utf-8", errors="replace") as f:
            for line_idx, line in enumerate(f, 1):
                line = line.strip()
                if not line.startswith("|"):
                    continue
                # Skip separator lines (e.g. |---|---|)
                if set(line) <= set("|-: "):
                    continue
                # Skip the first header row (column titles)
                if not header_seen:
                    header_seen = True
                    continue
                parts = [p.strip() for p in line.split("|")][1:-1]
                if len(parts) >= 7:
                    workspaces.append({
                        "name": parts[0],
                        "repo_path": parts[1],
                        "workspace": parts[2]
                    })
                else:
                    logger.warning(f"Skipping malformed line {line_idx} in index.md")
    except Exception as e:
        logger.error(f"Error parsing index file {index_path}: {e}")
    return workspaces

def load_fail_history(state_dir: str) -> list[str]:
    fail_path = os.path.join(state_dir, "fail_history")
    fingerprints = []
    if os.path.exists(fail_path):
        try:
            with open(fail_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        fingerprints.append(line)
        except Exception as e:
            logger.warning(f"Failed to read fail_history in {state_dir}: {e}")
    return fingerprints

def main():
    ap = argparse.ArgumentParser(description="Loop 4 Trace Collector & Aggregator")
    ap.add_argument("--index", default=os.path.expanduser("~/.loop/index.md"),
                    help="Path to index.md database")
    ap.add_argument("--out", default=None,
                    help="Output directory for snapshot.jsonl and summary.json")
    ap.add_argument("--k", type=int, default=2,
                    help="Min distinct repo count threshold for cross-project promotion")
    ap.add_argument("--since", default=None,
                    help="Filter rounds.jsonl traces starting from YYYY-MM-DD "
                         "(note: does NOT affect oscillation_hotspots which reads cumulative fail_history)")
    ap.add_argument("--enhanced-threshold", type=int, default=4,
                    help="Min enhanced rounds used to mark enhanced ineffective")
    args = ap.parse_args()

    # Determine output directories
    today_str = datetime.now().strftime("%F")
    out_dir = args.out or os.path.join(HERE, "..", "maintenance", "trace-snapshots", today_str)
    out_dir = os.path.realpath(out_dir)

    os.makedirs(out_dir, exist_ok=True)
    snapshot_path = os.path.join(out_dir, "snapshot.jsonl")
    summary_path = os.path.join(out_dir, "summary.json")

    # 1. Discover workspaces
    workspaces = parse_index_file(args.index)
    distinct_repos = {ws["repo_path"] for ws in workspaces}
    logger.info(f"Discovered {len(distinct_repos)} repos / {len(workspaces)} workspaces from index")

    all_rounds = []
    workspace_latest_run = {}  # ws_key -> latest_run_id
    workspace_fail_histories = {}  # ws_key -> list of fingerprints

    # 2. Collect traces from each workspace
    for ws in workspaces:
        ws_key = f"{ws['repo_path']}:{ws['workspace']}"
        state_dir = os.path.join(ws["repo_path"], ".loop", ws["workspace"], ".loop_state")
        rounds_path = os.path.join(state_dir, "rounds.jsonl")
        
        if not os.path.exists(rounds_path):
            logger.warning(f"Rounds log not found: {rounds_path}, skipping.")
            continue

        # Load fail_history for this workspace (first collect from rounds.jsonl, fallback to file if empty)
        fingerprints = []
        workspace_fail_histories[ws_key] = fingerprints

        # Parse rounds.jsonl
        try:
            with open(rounds_path, "r", encoding="utf-8", errors="replace") as f:
                for line_idx, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        # Inject workspace metadata
                        record["repo"] = os.path.basename(os.path.normpath(ws["repo_path"]))
                        record["ws"] = ws["workspace"]
                        record["repo_path"] = ws["repo_path"]
                        
                        # Extract fail fingerprint if exists
                        fp = record.get("fail_fingerprint")
                        if fp:
                            fingerprints.append(fp)
                        
                        # Apply --since filter if provided
                        if args.since:
                            ts_val = record.get("ts", "")
                            if ts_val and ts_val < args.since:
                                continue

                        all_rounds.append(record)
                        
                        # Track latest run_id for fail_history mapping
                        run_id = record.get("run_id")
                        if run_id:
                            workspace_latest_run[ws_key] = run_id
                    except json.JSONDecodeError as je:
                        logger.warning(f"Malformed JSON on line {line_idx} in {rounds_path}: {je}")
            
            # Fallback to loading fail_history from file if no fingerprints were extracted from rounds.jsonl
            if not fingerprints:
                workspace_fail_histories[ws_key] = load_fail_history(state_dir)
        except Exception as e:
            logger.error(f"Error reading rounds in {rounds_path}: {e}")

    # Write snapshot.jsonl
    try:
        with open(snapshot_path, "w", encoding="utf-8") as sf:
            for r in all_rounds:
                sf.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(f"Saved snapshot to {snapshot_path}")
    except Exception as e:
        logger.error(f"Failed to write snapshot.jsonl: {e}")

    # 3. Aggregate pain metrics
    # Group rounds by run_id
    runs_grouped = {}
    for r in all_rounds:
        run_id = r.get("run_id")
        if not run_id:
            continue
        if run_id not in runs_grouped:
            runs_grouped[run_id] = []
        runs_grouped[run_id].append(r)

    total_repos_count = len({r.get("repo_path", "") for r in all_rounds} - {""})
    total_ws_count = len({f"{r.get('repo_path', '')}:{r.get('ws', '')}" for r in all_rounds} - {":"})
    total_runs_count = len(runs_grouped)
    total_rounds_count = len(all_rounds)

    # 3.1 Escalation rate
    stuck_rounds = sum(1 for r in all_rounds if as_int(r.get("stuck_level")) >= 1)
    escalation_rate_overall = (stuck_rounds / total_rounds_count) if total_rounds_count > 0 else 0.0

    stuck_runs = {r.get("run_id") for r in all_rounds if as_int(r.get("stuck_level")) >= 1 and r.get("run_id")}

    # Escalation rate by phase
    rounds_by_phase = {}
    stuck_by_phase = {}
    for r in all_rounds:
        phase = str(r.get("phase", "unknown"))
        rounds_by_phase[phase] = rounds_by_phase.get(phase, 0) + 1
        if as_int(r.get("stuck_level")) >= 1:
            stuck_by_phase[phase] = stuck_by_phase.get(phase, 0) + 1

    escalation_by_phase = {}
    for phase, count in rounds_by_phase.items():
        escalation_by_phase[phase] = stuck_by_phase.get(phase, 0) / count

    # 3.2 Watchdog kill rate
    killed_rounds = sum(1 for r in all_rounds if r.get("killed"))
    watchdog_kill_rate_overall = (killed_rounds / total_rounds_count) if total_rounds_count > 0 else 0.0

    killed_runs = {r.get("run_id") for r in all_rounds if r.get("killed") and r.get("run_id")}

    rounds_by_kill_reason = {}
    for r in all_rounds:
        reason = r.get("killed")
        if reason:
            rounds_by_kill_reason[reason] = rounds_by_kill_reason.get(reason, 0) + 1

    watchdog_by_reason = {}
    for reason, count in rounds_by_kill_reason.items():
        watchdog_by_reason[reason] = count / total_rounds_count if total_rounds_count > 0 else 0.0

    # 3.3 Oscillation hotspots
    fingerprint_map = {}  # fp -> { "repos": set, "runs": set, "count": int }
    for ws_key, fingerprints in workspace_fail_histories.items():
        repo_name = os.path.basename(os.path.normpath(ws_key.rsplit(":", 1)[0]))
        latest_run = workspace_latest_run.get(ws_key)
        for fp in fingerprints:
            if fp not in fingerprint_map:
                fingerprint_map[fp] = {
                    "fingerprint": fp,
                    "count": 0,
                    "repos": set(),
                    "runs": set()
                }
            fingerprint_map[fp]["count"] += 1
            fingerprint_map[fp]["repos"].add(repo_name)
            if latest_run:
                fingerprint_map[fp]["runs"].add(latest_run)

    oscillation_hotspots = []
    for fp, info in fingerprint_map.items():
        if info["count"] >= 2:
            oscillation_hotspots.append({
                "fingerprint": fp,
                "count": info["count"],
                "repos": sorted(list(info["repos"])),
                "runs": sorted(list(info["runs"]))
            })

    # Sort hotspots by count descending
    oscillation_hotspots.sort(key=lambda h: h["count"], reverse=True)

    # 3.4 Non-converging streaks
    run_streaks = {}
    for run_id, rounds in runs_grouped.items():
        sorted_rounds = sorted(rounds, key=lambda r: (r.get("round", 0), r.get("ts", "")))
        max_streak = 0
        current_streak = 0
        for r in sorted_rounds:
            if not r.get("progressed", False):
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
            else:
                current_streak = 0
        run_streaks[run_id] = max_streak

    streak_values = list(run_streaks.values())
    if streak_values:
        max_streak_val = max(streak_values)
        sorted_streaks = sorted(streak_values)
        p95_idx = int(len(sorted_streaks) * 0.95)
        p95_streak_val = sorted_streaks[min(p95_idx, len(sorted_streaks) - 1)]
    else:
        max_streak_val = 0
        p95_streak_val = 0

    # 3.5 Enhanced ineffective
    enhanced_ineffective_list = []
    for run_id, rounds in runs_grouped.items():
        phases_in_run = {}
        for r in rounds:
            phase = str(r.get("phase", "unknown"))
            if phase not in phases_in_run:
                phases_in_run[phase] = []
            phases_in_run[phase].append(r)
            
        for phase, phase_rounds in phases_in_run.items():
            sorted_pr = sorted(phase_rounds, key=lambda r: (r.get("round", 0), r.get("ts", "")))
            max_enhanced = max([as_int(r.get("enhanced_rounds_used")) for r in sorted_pr] or [0])
            if max_enhanced >= args.enhanced_threshold:
                last_r = sorted_pr[-1]
                if not last_r.get("progressed", False):
                    enhanced_ineffective_list.append({
                        "run_id": run_id,
                        "repo": last_r.get("repo", "unknown"),
                        "phase": phase,
                        "enhanced_rounds_used": max_enhanced,
                        "still_stuck": True
                    })

    # 3.6 Pass reset rate
    total_resets = 0
    resets_by_phase = {}
    rounds_by_phase_reset = {}
    reset_runs = set()

    for run_id, rounds in runs_grouped.items():
        sorted_rounds = sorted(rounds, key=lambda r: (r.get("round", 0), r.get("ts", "")))
        prev_pass_by_phase = {}
        for r in sorted_rounds:
            phase = str(r.get("phase", "unknown"))
            rounds_by_phase_reset[phase] = rounds_by_phase_reset.get(phase, 0) + 1
            curr_pass = as_int(r.get("consecutive_pass"))
            prev_pass = prev_pass_by_phase.get(phase)
            if prev_pass is not None and prev_pass > 0 and curr_pass == 0:
                total_resets += 1
                resets_by_phase[phase] = resets_by_phase.get(phase, 0) + 1
                reset_runs.add(run_id)
            prev_pass_by_phase[phase] = curr_pass

    pass_reset_rate_overall = (total_resets / total_rounds_count) if total_rounds_count > 0 else 0.0
    pass_reset_by_phase = {}
    for phase, count in rounds_by_phase_reset.items():
        pass_reset_by_phase[phase] = resets_by_phase.get(phase, 0) / count

    # Compile cross-project candidates
    cross_project_candidates = []

    # Hotspot Candidates
    for h in oscillation_hotspots:
        distinct_repos_count = len(h["repos"])
        meets_K = distinct_repos_count >= args.k
        cross_project_candidates.append({
            "signal_key": f"oscillation:{h['fingerprint']}",
            "kind": "oscillation_hotspot",
            "distinct_repos": distinct_repos_count,
            "count": h["count"],
            "meets_K": meets_K,
            "prelabel": "HARNESS_DEFECT_CANDIDATE",
            "evidence": {
                "repos": h["repos"],
                "runs": h["runs"],
                "fingerprint": h["fingerprint"]
            }
        })

    # Enhanced Ineffective Candidates
    enhanced_by_phase = {}
    for item in enhanced_ineffective_list:
        phase = item["phase"]
        if phase not in enhanced_by_phase:
            enhanced_by_phase[phase] = []
        enhanced_by_phase[phase].append(item)

    for phase, items in enhanced_by_phase.items():
        distinct_repos = sorted(list({item["repo"] for item in items}))
        distinct_runs = sorted(list({item["run_id"] for item in items}))
        distinct_repos_count = len(distinct_repos)
        meets_K = distinct_repos_count >= args.k
        cross_project_candidates.append({
            "signal_key": f"enhanced_ineffective:phase{phase}",
            "kind": "enhanced_ineffective",
            "distinct_repos": distinct_repos_count,
            "count": len(items),
            "meets_K": meets_K,
            "prelabel": "SPEC_CONFLICT_SUSPECT",
            "evidence": {
                "repos": distinct_repos,
                "runs": distinct_runs,
                "phase": phase
            }
        })

    # 4. Generate summary.json structure
    summary_data = {
        "generated_at": datetime.now().strftime("%F %T"),
        "snapshot": os.path.relpath(snapshot_path, os.path.join(HERE, "..")),
        "k": args.k,
        "totals": {
            "repos": total_repos_count,
            "workspaces": total_ws_count,
            "runs": total_runs_count,
            "rounds": total_rounds_count
        },
        "metrics": {
            "escalation_rate": {
                "overall": round(escalation_rate_overall, 4),
                "by_phase": {p: round(v, 4) for p, v in escalation_by_phase.items()},
                "evidence_runs": sorted(list(stuck_runs))
            },
            "watchdog_kill_rate": {
                "overall": round(watchdog_kill_rate_overall, 4),
                "by_reason": {r: round(v, 4) for r, v in watchdog_by_reason.items()},
                "evidence_runs": sorted(list(killed_runs))
            },
            "oscillation_hotspots": oscillation_hotspots,
            "non_converging_streaks": {
                "max": max_streak_val,
                "p95": p95_streak_val,
                "evidence_runs": sorted(list(run_streaks.keys()))
            },
            "enhanced_ineffective": enhanced_ineffective_list,
            "pass_reset_rate": {
                "overall": round(pass_reset_rate_overall, 4),
                "by_phase": {p: round(v, 4) for p, v in pass_reset_by_phase.items()},
                "evidence_runs": sorted(list(reset_runs))
            }
        },
        "cross_project_candidates": cross_project_candidates
    }

    try:
        with open(summary_path, "w", encoding="utf-8") as sf:
            json.dump(summary_data, sf, ensure_ascii=False, indent=2)
        logger.info(f"Saved summary to {summary_path}")
    except Exception as e:
        logger.error(f"Failed to write summary.json: {e}")

    # Summary stdout report
    print(f"\n--- COLLECTOR SUMMARY ---")
    print(f"Total Repos:      {total_repos_count}")
    print(f"Total Workspaces: {total_ws_count}")
    print(f"Total Runs:       {total_runs_count}")
    print(f"Total Rounds:     {total_rounds_count}")
    print(f"Candidates found: {len(cross_project_candidates)} (Meets K={args.k}: {sum(1 for c in cross_project_candidates if c['meets_K'])})")
    print(f"-------------------------\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
