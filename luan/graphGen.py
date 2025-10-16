def _generate_a_graph_worker(args):
    n, O = args
    return generate_a_graph(n, O)


import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
import multiprocessing


# pi -> pj 表示pi信任pj，pj in UNL_i


def fill_line(start, constraint, i, ni):
    # 找出所有可选的列
    pos_candidates = [
        j for j in range(start.shape[1]) if start[i, j] == 0 and constraint[i, j] > 0
    ]
    neg_candidates = [
        j for j in range(start.shape[1]) if start[i, j] == 0 and constraint[i, j] <= 0
    ]

    if len(pos_candidates) >= ni:
        chosen = np.random.choice(pos_candidates, ni, replace=False)
    else:
        chosen = pos_candidates.copy()
        need = ni - len(pos_candidates)
        if len(neg_candidates) < need:
            raise ValueError("可选位置不足")
        chosen += list(np.random.choice(neg_candidates, need, replace=False))
    for j in chosen:
        start[i, j] = 1
    # 更新constraint
    n = start.shape[0]
    for j in range(n):
        if i == j:
            continue
        UNL_i = set(np.where(start[i] == 1)[0])
        UNL_j = set(np.where(start[j] == 1)[0])
        overlap = len(UNL_i & UNL_j)
        min_len = min(len(UNL_i), len(UNL_j)) if min(len(UNL_i), len(UNL_j)) > 0 else 1
        # 这里假设O是全局变量或传参
        constraint[i, j] = constraint[i, j] - (overlap / min_len)


def generate_a_graph(n, O):
        # 新算法：先生成多个UNL集合，满足重叠率条件，再随机分配给每个节点
        # 设定UNL数量和每个UNL的大小
    max_attempt = 1000
    def overlap_rate(a, b):
        if not a or not b:
            return 0
        return len(a & b) / min(len(a), len(b))
    for _ in range(max_attempt):
        UNL_count = max(1, np.random.randint(1, n + 1))
        UNLs = []
        for _ in range(UNL_count):
            UNL_size = np.random.randint(1, n + 1)
            UNL_size = min(UNL_size, n)
            base = set(np.random.choice(range(n), UNL_size, replace=False))
            UNLs.append(base)
        valid = True
        for i in range(UNL_count):
            for j in range(i+1, UNL_count):
                if overlap_rate(UNLs[i], UNLs[j]) < O:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            break
        # 给每个节点随机分配一个UNL
        node_UNL_indices = np.random.choice(range(UNL_count), n, replace=True)
        # 构造邻接矩阵
        adj = np.zeros((n, n), dtype=int)
        for i in range(n):
            UNL = UNLs[node_UNL_indices[i]]
            for j in UNL:
                adj[i, j] = 1
        G = nx.from_numpy_array(adj, create_using=nx.DiGraph)
        if check(G, O):
            return G
        else:
            return None


def check(G, O):
    for i in G.nodes:
        UNL_i = set(G.neighbors(i))
        # print(f"node {i}, UNL: {UNL_i}")
        for j in G.nodes:
            if j == i:
                continue
            UNL_j = set(G.neighbors(j))
            overlap = UNL_i & UNL_j
            o = len(overlap)
            # print(f"overlap of {i} and {j}: {overlap}")
            if (o / len(UNL_i) >= O) & (o / len(UNL_j) >= O):
                continue
            else:
                # print("overlap check failed")
                return False
    return True


def generate_graph(N, n, O):
    # 反复调用 generate_a_graph(n, O)，直到生成N个满足条件的图
    graphs = []
    k = 0
    cpu_count = multiprocessing.cpu_count()
    batch_size = max(N * 2, cpu_count * 4)
    graph_hashes = []
    # 使用上下文管理器自动管理进程池
    with multiprocessing.Pool(cpu_count) as pool:
        while len(graphs) < N:
            candidates = pool.map(_generate_a_graph_worker, [(n, O)] * batch_size)
            for g in candidates:
                if g is None:
                    continue
                if not nx.is_weakly_connected(g):
                    continue
                h = nx.weisfeiler_lehman_graph_hash(g)
                possible_indices = [i for i, h_exist in enumerate(graph_hashes) if h == h_exist]
                is_duplicate = False
                if possible_indices:
                    for idx in possible_indices:
                        if nx.is_isomorphic(g, graphs[idx]):
                            is_duplicate = True
                            break
                if is_duplicate:
                    continue
                graphs.append(g)
                graph_hashes.append(h)
                k += 1
                print(f"生成第 {k} 个满足条件的图")
                plt.figure(figsize=(6, 6))
                nx.draw(g, with_labels=True)
                plt.savefig(f"out/g_n_{n}_o_{O}_{k}.pdf")
                plt.close()
                # 输出UNL partition到txt
                unl_partition = []
                for i in range(n):
                    unl = list(g.successors(i))
                    unl_partition.append([i] + unl)
                with open(f"out/{n}_node_{O}_overlap.txt", "a") as f:
                    f.write(f"unl_partition: {unl_partition}\n\n")
                if len(graphs) >= N:
                    break
    if len(graphs) < N:
        print(f"只生成了 {len(graphs)} 个满足条件的图")
    return graphs


def main():

    g = np.array(
        [
            [1, 1, 1, 1, 1, 0, 0],
            [1, 1, 1, 1, 1, 0, 0],
            [1, 1, 1, 1, 1, 0, 0],
            [1, 1, 1, 1, 1, 0, 0],
            [0, 0, 1, 1, 1, 1, 1],
            [0, 0, 1, 1, 1, 1, 1],
            [0, 0, 1, 1, 1, 1, 1],
        ]
    )

    G = nx.from_numpy_array(g, create_using=nx.DiGraph)
    check(G, 0.5)
    # plt.figure(figsize=(6,6))
    # nx.draw(G, with_labels=True)
    #
    # plt.savefig("out/g.pdf")
    # plt.close()
    s = 25
    for n in range(s, s+5):
        generate_graph(n, n, 0.9)


if __name__ == "__main__":
    main()
