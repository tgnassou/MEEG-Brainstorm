import pandas as pd
import argparse
import matplotlib.pyplot as plt
from pathlib import Path
import seaborn as sns


def get_parser():
    """Set parameters for the experiment."""
    parser = argparse.ArgumentParser(
        "spike detection", description="spike detection using attention layer"
    )
    parser.add_argument("--path_data", type=str, default="../results/csv")
    parser.add_argument("--n_subjects", type=int, default=1)

    return parser


# Experiment name
parser = get_parser()
args = parser.parse_args()  # you can modify this namespace for quick iterations
path_data = args.path_data
n_subjects = args.n_subjects

fnames = list(
    Path(path_data).glob("results_LOPO_spike_detection_method-*_{}-subjects.csv".format(n_subjects))
)
df = pd.concat([pd.read_csv(fname) for fname in fnames], axis=0)
df["method"] = df["method"].replace({"transformer_classification": "STT"})
# fig = plt.figure()
# sns.boxplot(data=df, x="balance", y="f1", palette="Set2")
# sns.swarmplot(data=df, x="balance", y="f1", hue="test_subj_id", palette="Spectral")
# plt.legend([],[], frameon=False)
# plt.title(f"Results for F1 score")
# plt.tight_layout()


# fig.savefig(
#      "../results/images/results_f1_score_{}_subjects.pdf".format(n_subjects),
#     bbox_inches="tight",
# )

# fig = plt.figure()
# sns.boxplot(data=df, x="balance", y="acc", palette="Set2" )
# sns.swarmplot(data=df, x="method", y="acc", color=".25")
# plt.title(f"Results for accuracy score")
# plt.tight_layout()


# fig.savefig(
#      "../results/images/results_acc_score_{}_subjects.pdf".format(n_subjects),
#     bbox_inches="tight",
# )
g = sns.FacetGrid(df, row="mix_up", col="cost_sensitive", margin_titles=True)
g.map(sns.boxplot, "weight_loss", "f1", "method", palette="Set2") #, fit_reg=False, x_jitter=.1)
g.add_legend()
# g.fig.suptitle('LOPO')
g.savefig(
     "../results/images/results_LOPO_F1_score_{}_subjects.pdf".format(n_subjects),
    bbox_inches="tight",
)

g = sns.FacetGrid(df.loc[(df['mix_up'] == False) & (df['cost_sensitive'] == False)], col="weight_loss", margin_titles=True)
g.map(sns.boxplot, "method", "f1", palette="Set2") #, fit_reg=False, x_jitter=.1)
g.map(sns.swarmplot, "method", "f1", "test_subject_id", palette="tab10") #, fit_reg=False, x_jitter=.1)
g.add_legend()
g.fig.suptitle('LOPO')
g.savefig(
     "../results/images/results_LOPO_F1_score_swarmplot_{}_subjects.pdf".format(n_subjects),
    bbox_inches="tight",
)

print(df.groupby(['method', 'mix_up', 'cost_sensitive', 'weight_loss']).mean().reset_index())
print(df.groupby(['method', 'mix_up', 'cost_sensitive', 'weight_loss']).std().reset_index())
