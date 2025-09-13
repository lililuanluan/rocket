import matplotlib.pyplot as plt
import pandas as pd

CUR_RUN = "2025_09_07_13h37m"

file_path = f"./logs/{CUR_RUN}/state_coverage.csv"
df = pd.read_csv(file_path)

plt.figure(figsize=(8, 5))
plt.plot(df["iteration"], df["unique_states"], marker="o")

# Paper uses log-scale for x-axis. (Learning-based controlled concurrency testing [https://dl.acm.org/doi/pdf/10.1145/3428298])
plt.xscale("log", base=2)
plt.xlabel("Iteration")
plt.ylabel("Unique States")
plt.title("Unique States vs Iteration")
plt.grid(True)
plt.show()
