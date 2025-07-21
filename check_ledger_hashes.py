import os
import re
from collections import defaultdict

def collect_logs_and_check_hashes(base_log_dir):
    # Regex patterns to match TMStatusChange logs
    accepted_pattern = re.compile(r'False,TMStatusChange,"newEvent: neACCEPTED_LEDGER; ledgerSeq: (\d+);')
    closing_pattern = re.compile(r'False,TMStatusChange,"newEvent: neCLOSING_LEDGER; ledgerSeq: (\d+); ledgerHash: "(.*?)";')

    rip_agreement = 0
    rip_termination = 0
    rip_agreement_iterations = []
    rip_termination_iterations = []

    for iteration in range(1, 101):
        ledger_hashes = defaultdict(list)
        contains_ledger_seq_20 = False
        log_dir = os.path.join(base_log_dir, f"iteration-{iteration}", f"action-{iteration}.csv")
        if not os.path.exists(log_dir):
            print(f"Log file not found: {log_dir}")
            continue

        with open(log_dir, "r") as f:
            for line in f:
                accepted_match = accepted_pattern.search(line)
                closing_match = closing_pattern.search(line)

                if accepted_match:
                    seq = int(accepted_match.group(1))
                    ledger_hashes[seq].append({"type": "accepted", "line": line.strip()})
                    if seq == 15:
                        contains_ledger_seq_20 = True

                if closing_match:
                    seq = int(closing_match.group(1))
                    ledger_hash = closing_match.group(2)
                    ledger_hashes[seq].append({"type": "closing", "ledger_hash": ledger_hash, "line": line.strip()})

        agreement = True
        for seq, logs in ledger_hashes.items():
            closing_hashes = [log["ledger_hash"] for log in logs if log["type"] == "closing"]
            if len(set(closing_hashes)) > 1:
                print(f"Disagreement found in iteration {iteration} for ledger sequence {seq}: {closing_hashes}")
                agreement = False
                break

        if not agreement and not contains_ledger_seq_20:
            print(f"Iteration {iteration}: Agreement: false, Reached goal seq: false")
            rip_agreement += 1
            rip_agreement_iterations.append(iteration)
            rip_termination += 1
            rip_termination_iterations.append(iteration)
        elif not agreement and contains_ledger_seq_20:
            print(f"Iteration {iteration}: Agreement: false, Reached goal seq: true")
            rip_agreement += 1
            rip_agreement_iterations.append(iteration)
        elif agreement and not contains_ledger_seq_20:
            print(f"Iteration {iteration}: Agreement: true, Reached goal seq: false")
            rip_termination += 1
            rip_termination_iterations.append(iteration)
        else:
            print(f"Iteration {iteration}: Agreement: true, Reached goal seq: true")

    print(f"\nTotal iterations with agreement: {rip_agreement} ({rip_agreement_iterations})")
    print(f"Total iterations with termination: {rip_termination} ({rip_termination_iterations})")

if __name__ == "__main__":
    base_log_directory = "/home/aistemaci/rocket-1/logs/2025_06_08_19h46m/xrpld-2.4.0-100UNL-drop-0.1_corrupt-0.1"
    collect_logs_and_check_hashes(base_log_directory)
