import os
import csv
from collections import defaultdict

def collect_logs_and_check_hashes(base_log_dir):
    rip_agreement = 0
    rip_termination = 0
    rip_agreement_iterations = []
    rip_termination_iterations = []

    termination_fork_iterations = []
    termination_fork = 0
    good_run_iterations = []
    good_run = 0
    rip_termination_iterations = []
    rip_termination = 0

    for iteration in range(1, 101):
        ledger_hashes = defaultdict(list)
        contains_goal_seq = False
        log_dir = os.path.join(base_log_dir, f"iteration-{iteration}", f"ledger-{iteration}.csv")
        if not os.path.exists(log_dir):
            print(f"Log file not found: {log_dir}")
            continue
        ledger_hashes_validated = defaultdict(list)

        with open(log_dir, "r") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if "validated" in row["ledger_seq"]:
                    # Extract the sequence number from the validated ledger sequence
                    #validated_seq = int(row["ledger_seq"].split("-")[1])
                    #validated = row["validated"] == "True"
                    #if validated:
                    #    ledger_hashes_validated[validated_seq].append(validated_seq)
                    continue
                seq = int(row["ledger_seq"])
                validated = row["validated"] == "True"
                ledger_hash = row["ledger_hash"]

                if validated:
                    ledger_hashes[seq].append(ledger_hash)

        validated_seqs = list(ledger_hashes_validated.keys())
        if validated_seqs:
            all_same_seq = all(seq == validated_seqs[0] for seq in validated_seqs)
            if not all_same_seq:
                termination_fork_iterations.append(iteration)
                termination_fork += 1
                print(f"Disagreement in validated ledger sequences in iteration {iteration}: {validated_seqs}")
            if all_same_seq and validated_seqs[0] == 14:
                good_run_iterations.append(iteration)
                good_run += 1
            else:
                rip_termination_iterations.append(iteration)
                rip_termination += 1

            print(f"All validated ledger sequences are 14 in iteration {iteration}")

        agreement = True
        for seq, hashes in ledger_hashes.items():
            if len(set(hashes)) > 1:
                print(f"Disagreement found in iteration {iteration} for ledger sequence {seq}: {hashes}")
                agreement = False
                break

        if not agreement:
            print(f"Iteration {iteration}: Agreement: false")
            rip_agreement += 1
            rip_agreement_iterations.append(iteration)
        else:
            print(f"Iteration {iteration}: Agreement: true")

    print("Dont forget to check for byzantine nodes... There is one...")
    print(f"\nTotal iterations with agreement: {rip_agreement} ({rip_agreement_iterations})")
    print(f"Total iterations with termination fork: {termination_fork} ({termination_fork_iterations})")
    print(f"Total iterations with good run: {good_run} ({good_run_iterations})")
    print(f"Total iterations with termination: {rip_termination} ({rip_termination_iterations})")

if __name__ == "__main__":
    base_log_directory = "/home/aistemaci/rocket-1/logs/2025_06_17_06h16m/xrpld-2.4.0-60UNL-small_scope_process_faults-2_network_faults-2"
    collect_logs_and_check_hashes(base_log_directory)
