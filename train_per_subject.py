#!/usr/bin/env python

"""
This script is used to train models.

Contributors: Ambroise Odonnat and Theo Gnassounou.
"""

import argparse
import os
from platform import architecture
import numpy as np
import pandas as pd

from loguru import logger
from torch.nn import BCELoss
from torch.optim import Adam

from models.architectures import RNN_self_attention, STT
from models.training import make_model
from loader.dataloader import Loader
from loader.data import Data
from utils.cost_sensitive_loss import get_criterion
from utils.utils_ import define_device, reset_weights


def get_parser():

    """ Set parameters for the experiment."""

    parser = argparse.ArgumentParser(
        "Spike detection", description="Spike detection using attention layer"
    )
    parser.add_argument("--path_root", type=str, default="../BIDSdataset/")
    parser.add_argument("--method", type=str, default="RNN_self_attention")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--average", type=str, default="binary")
    parser.add_argument("--n_windows", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--n_epochs", type=int, default=100)
    parser.add_argument("--cost_sensitive", action="store_true")
    parser.add_argument("--lambd", type=float, default=1e-4)
    parser.add_argument("--mix_up", action="store_true")
    parser.add_argument("--beta", type=float, default=0.4)

    return parser


# Experiment name
parser = get_parser()
args = parser.parse_args()
path_root = args.path_root
method = args.method
save = args.save
average = args.average
n_windows = args.n_windows
batch_size = args.batch_size
num_workers = args.num_workers
n_epochs = args.n_epochs
cost_sensitive = args.cost_sensitive
lambd = args.lambd
mix_up = args.mix_up
beta = args.beta

# Recover params
lr = 1e-3  # Learning rate
patience = 10
weight_decay = 0
gpu_id = 0

# Define device
available, device = define_device(gpu_id)

# Define loss
criterion = BCELoss().to(device)
train_criterion = get_criterion(criterion,
                                cost_sensitive,
                                lambd)

# Recover results
results = []
mean_acc, mean_f1, mean_precision, mean_recall = 0, 0, 0, 0
steps = 0

# Recover dataset
assert method in ("RNN_self_attention", "transformer_classification",
                  "transformer_detection")

logger.info(f"Method used: {method}")
if method == 'RNN_self_attention':
    single_channel = True
else:
    single_channel = False

dataset = Data(path_root, 'spikeandwave', single_channel, n_windows)
data, labels, spikes, sfreq = dataset.all_datasets()
subject_ids = np.asarray(list(data.keys()))

# Apply Leave-One-Patient-Out strategy

""" Each subject is chosen once as test set while the model is trained
    and validate on the remaining ones.
"""

for train_subject_id in subject_ids:
    # Training dataloader
    data_list = []
    labels_list = []
    spikes_list = []
    data_list.append(data[train_subject_id])
    labels_list.append(labels[train_subject_id])
    spikes_list.append(spikes[train_subject_id])

    for seed in range(5):

        # Dataloader
        if method == "transformer_detection":

            # Labels are the spike events times
            loader = Loader(data_list,
                            spikes_list,
                            balanced=False,
                            shuffle=True,
                            batch_size=batch_size,
                            num_workers=num_workers,
                            split_dataset=True,
                            seed=seed)
        else:

            # Label is 1 with a spike occurs in the trial, 0 otherwise
            loader = Loader(data_list,
                            labels_list,
                            balanced=False,
                            shuffle=True,
                            batch_size=batch_size,
                            num_workers=num_workers,
                            split_dataset=True,
                            seed=seed)
        train_dataloader, val_dataloader, test_dataloader = loader.load()

        # Define architecture
        if method == "RNN_self_attention":
            architecture = RNN_self_attention()
        elif method == "transformer_classification":
            architecture = STT(n_windows=n_windows)
        elif method == "transformer_detection":
            detection = True
            architecture = STT(n_windows=n_windows, detection=detection)
        architecture.apply(reset_weights)

        # Define optimizer
        optimizer = Adam(architecture.parameters(), lr=lr,
                        weight_decay=weight_decay)

        # Define training pipeline
        architecture = architecture.to(device)

        model = make_model(architecture,
                        train_dataloader,
                        val_dataloader,
                        test_dataloader,
                        optimizer,
                        train_criterion,
                        criterion,
                        n_epochs=n_epochs,
                        patience=patience,
                        average=average,
                        mix_up=mix_up,
                        beta=beta)

        # Train Model
        history = model.train()

        if not os.path.exists("../results"):
            os.mkdir("../results")

        # Compute test performance and save it
        metrics = model.score()
        acc, f1, precision, recall = metrics[:4]
        f1_macro, precision_macro, recall_macro = metrics[4:]
        results.append(
            {
                "method": method,
                "mix_up": mix_up,
                "cost_sensitive": cost_sensitive,
                "subject_id": train_subject_id,
                "fold": seed,
                "acc": acc,
                "f1": f1,
                "precision": precision,
                "recall": recall,
                "f1_macro": f1_macro,
                "precision_macro": precision_macro,
                "recall_macro": recall_macro,
            }
        )
        mean_acc += acc
        mean_f1 += f1
        mean_precision += precision
        mean_recall += recall
        steps += 1
        if save:

            # Save results file as csv
            if not os.path.exists("../results"):
                os.mkdir("../results")

            results_path = (
                "../results/csv"
            )
            if not os.path.exists(results_path):
                os.mkdir(results_path)

            df_results = pd.DataFrame(results)
            df_results.to_csv(
                os.path.join(results_path,
                            "results_intra_subject_spike_detection_method-{}"
                            "_mix-up-{}_cost-sensitive-{}_{}"
                            "-subjects.csv".format(method,
                                                    mix_up,
                                                    cost_sensitive,
                                                    len(subject_ids))
                            )
                )
    print("Mean accuracy \t Mean F1-score \t Mean precision \t Mean recall")
    print("-" * 80)
    print(
        f"{mean_acc/steps:0.4f} \t {mean_f1/steps:0.4f} \t"
        f"{mean_precision/steps:0.4f} \t {mean_recall/steps:0.4f}\n"
    )