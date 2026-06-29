import json
import os
import re
import subprocess
import sys


def log(msg: str):
    print(msg, file=sys.stderr)


def load_text_from_prompt(prompt: str, pattern: str, default: str) -> str:
    match = re.search(pattern, prompt)
    return match.group(1).strip('`"\'') if match else default


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()

    if '???' in prompt or '1-plan-generator' in prompt or 'state.json' in prompt:
        log('Detected Plan Generation Prompt.')
        state_json = load_text_from_prompt(prompt, r'(\S+state\.json)', '.loop/default/state.json')
        phase_dir = '.loop/default/phases'
        phase1_md = os.path.join(phase_dir, 'PHASE1.md')

        changed = False
        if not os.path.exists(state_json):
            changed = True
            log('Generating state.json and PHASE1.md...')
            os.makedirs(os.path.dirname(state_json), exist_ok=True)
            os.makedirs(phase_dir, exist_ok=True)
            state = {
                'current_phase': '1',
                'plan_version': 1,
                'framework_ref': '',
                'control': {
                    'last_round_mode': '',
                    'last_round_result': '',
                    'last_round_fail_tasks': '',
                    'rounds_since_progress': 0,
                    'stuck_level': 0,
                    'current_model_tier': '',
                    'enhanced_rounds_used': 0,
                    'human_required': False,
                    'stop_condition_met': False,
                },
                'phases': [
                    {
                        'id': 1,
                        'consecutive_pass': 0,
                        'total_validations': 0,
                        'last_result': '',
                        'tasks': [
                            {'id': 'TASK-01', 'status': 'TODO', 'conv': 0, 'output': 'src/hello.py'}
                        ],
                    }
                ],
                'issues': [],
                'requirements_map': [
                    {'requirement_id': 'R001', 'task_id': 'TASK-01', 'check': 'run hello.py'}
                ],
            }
            with open(state_json, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            with open(phase1_md, 'w', encoding='utf-8') as f:
                f.write('# PHASE1\n\n## TASK-01\n- output: src/hello.py\n- validation: run hello.py\n')

        if os.path.exists(plan_md):
            with open(plan_md, 'r', encoding='utf-8') as f:
                plan_lines = f.readlines()
            new_plan_lines = []
            for line in plan_lines:
                if line.startswith('plan_changed_last:'):
                    new_plan_lines.append(f"plan_changed_last: {'true' if changed else 'false'}\n")
                else:
                    new_plan_lines.append(line)
            with open(plan_md, 'w', encoding='utf-8') as f:
                f.writelines(new_plan_lines)

        subprocess.run(['git', 'add', '-A'])
        subprocess.run(['git', 'commit', '-m', f'Plan update (changed={changed})'])
        sys.exit(0)

    if 'BOOT SEQUENCE' in prompt or 'boot-sequence' in prompt:
        log('Detected Execution/Base Prompt.')
        state_json = '.loop/default/state.json'
        with open(state_json, 'r', encoding='utf-8') as f:
            state = json.load(f)

        phase = state.get('phases', [{}])[0]
        task = phase.get('tasks', [{}])[0]
        p1_pass = int(phase.get('consecutive_pass', 0))

        if task.get('status') == 'TODO':
            log('Task is TODO. Transitioning to CONVERGED.')
            os.makedirs('src', exist_ok=True)
            with open('src/hello.py', 'w', encoding='utf-8') as f:
                f.write("print('Hello from Loop Agent')\n")
            task['status'] = 'CONVERGED'
            task['conv'] = 1
            state['control']['last_round_mode'] = '??'
            state['control']['last_round_result'] = 'PASS'
            os.makedirs('src/.reverify', exist_ok=True)
            with open('src/.reverify/TASK-01-R001.md', 'w', encoding='utf-8') as f:
                f.write('# Reverify TASK-01\nPASS')
            with open(state_json, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            subprocess.run(['git', 'add', '-A'])
            subprocess.run(['git', 'commit', '-m', 'R001 | phase1 | TASK-01 | ?? | hello.py created'])
            sys.exit(0)

        if task.get('status') == 'CONVERGED':
            if p1_pass == 0:
                log('All tasks converged. Running validation.')
                phase['consecutive_pass'] = 1
                state['control']['last_round_mode'] = '??'
                state['control']['last_round_result'] = 'PASS'
                os.makedirs('src/.validate', exist_ok=True)
                with open('src/.validate/p1-R002.md', 'w', encoding='utf-8') as f:
                    f.write('# Validation p1-R002\n- result: PASS\n[MOCK TEST OUTPUT] All green\n')
                with open(state_json, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
                subprocess.run(['git', 'add', '-A'])
                subprocess.run(['git', 'commit', '-m', 'R002 | phase1 | ?? | PASS'])
                sys.exit(0)
            print('LOOP COMPLETE')
            sys.exit(0)

    log(f'Unknown prompt type. Prompt: {prompt[:100]}')
    sys.exit(1)


if __name__ == '__main__':
    main()
