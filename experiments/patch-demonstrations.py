# %%
%reload_ext autoreload
%autoreload 2

# Install procgen tools if needed
try:
  import procgen_tools
except ImportError:
  get_ipython().run_line_magic(magic_name='pip', line='install git+https://github.com/ulissemini/procgen-tools')

# %%
# Download data and create directory structure

import os, sys
from pathlib import Path
from procgen_tools.utils import setup

setup() # create directory structure and download data

# path this notebook expects to be in
if 'experiments' not in os.getcwd():
    Path('experiments').mkdir(exist_ok=True)
    os.chdir('experiments')

# %%
# Imports
from typing import List, Tuple, Dict, Union, Optional, Callable

import numpy as np
import pandas as pd
import torch as t
import plotly.express as px
import plotly as py
import plotly.graph_objects as go
from tqdm import tqdm
from einops import rearrange
from IPython.display import Video, display, clear_output
from ipywidgets import *
import itertools
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
import matplotlib.pyplot as plt 
plt.ioff() # disable interactive plotting, so that we can control where figures show up when refreshed by an ipywidget

import circrl.module_hook as cmh
import procgen_tools.models as models
from procgen_tools.patch_utils import *
from procgen_tools.vfield import *
from procgen import ProcgenGym3Env

# %%
# Check whether we're in jupyter
try:
    get_ipython()
    in_jupyter = True
except NameError:
    in_jupyter = False
path_prefix = '../' if in_jupyter else ''

# Load model
rand_region = 5
policy = models.load_policy(path_prefix + f'trained_models/maze_I/model_rand_region_{rand_region}.pth', 15, t.device('cpu'))
hook = cmh.ModuleHook(policy)

main_label = 'embedder.block2.res1.resadd_out'

hook.run_with_input(np.zeros((1,3, 64, 64), dtype=np.float32))
labels = list(hook.values_by_label.keys()) # all labels in the model
if '_out' in labels: labels.remove('_out')

# RUN ABOVE here; the rest are one-off experiments which don't have to be run in sequence
# %% Sanity-check that the patching performance is not changed at the original square
@interact
def sanity_check(label=Dropdown(options=labels), seed=IntSlider(min=0, max=20, step=1, value=0)):
    cheese_pair = get_cheese_venv_pair(seed, has_cheese_tup = (False, True))

    # Visualize the cheese pair to make sure we've got the environment right
    fig, ax = plt.subplots(1, 2, figsize=(10, 5))
    ax[0].imshow(cheese_pair.env.get_info()[0]['rgb'])
    ax[1].imshow(cheese_pair.env.get_info()[1]['rgb'])
    plt.show()

    values = cheese_diff_values(seed, label, hook)
    patches = get_values_diff_patch(values, coeff=-1, label=label)

    original_vfield = vfield.vector_field(copy_venv(cheese_pair, 0), hook.network)
    with hook.use_patches(patches):
        patched_vfield = vfield.vector_field(copy_venv(cheese_pair, 1), hook.network)

    # Plot the vfield diff
    fig, axs = plot_vfs_with_diff(original_vfield, patched_vfield)
    plt.show(block=True)

    mouse_pos = maze.get_mouse_pos(maze.get_inner_grid_from_seed(seed))
    mouse_idx = original_vfield['legal_mouse_positions'].index(mouse_pos)
    orig_arrow = original_vfield['arrows'][mouse_idx]
    patch_arrow = patched_vfield['arrows'][mouse_idx]
    diff = np.linalg.norm(np.array(orig_arrow) - np.array(patch_arrow))
    print(f'Seed {seed} has difference {diff:.3f}')

# %% Vfields on each maze
""" The vector field is a plot of the action probabilities for each state in the maze. Let's see what the vector field looks like for a given seed. We'll compare the vector field for the original and patched networks. 
"""
@interact
def interactive_patching(seed=IntSlider(min=0, max=20, step=1, value=0), coeff=FloatSlider(min=-3, max=3, step=0.1, value=-1)):
    fig, _, _ = plot_patched_vfields(seed, coeff, main_label, hook)
    plt.show()

# %% Patching from a fixed seed
""" Let's see what happens when we patch the network from a fixed seed. We'll compare the vector field for the original and patched networks.
"""
value_seed = 0
values_tup = cheese_diff_values(value_seed, main_label, hook), value_seed
for seed in range(10):  
    run_seed(seed, hook, [-1], values_tup=values_tup)

# %% We can construct a patch which averages over a range of seeds, and see if that generalizes better (it doesn't)
seeds = slice(int(10e5),int(10e5+19))
last_labels = ['embedder.block3.res2.conv2_out', 'embedder.block3.res2.resadd_out', 'embedder.relu3_out', 'embedder.flatten_out', 'embedder.fc_out', 'embedder.relufc_out']
@interact
def interactive_patching(target_seed=IntSlider(min=0, max=20, step=1, value=0), coeff=FloatSlider(min=-2, max=2, step=0.1, value=-1), label=Dropdown(options=last_labels, value=last_labels[0])):
    values = np.zeros_like(cheese_diff_values(0, label, hook))
    for seed in range(seeds.start, seeds.stop):
        # Make values be rolling average of values from seeds
        values = (seed-seeds.start)/(seed-seeds.start+1)*values + cheese_diff_values(seed, label, hook)/(seed-seeds.start+1)

    fig, _, _ = plot_patched_vfields(target_seed, coeff, label, hook, values=values)
    plt.show()

# %% Patching with a random vector 
""" Are we just seeing noise? Let's try patching with a random vector and see if that works. First, let's find appropriate-magnitude random vectors."""
rand_magnitude = .25
for mode in ['random', 'cheese']:
    vectors = []
    for value_seed in range(100):
        if mode == 'random':
            vectors.append(np.random.randn(*cheese_diff_values(0, main_label, hook).shape, ) * rand_magnitude)
        else:
            vectors.append(cheese_diff_values(value_seed, main_label, hook))
        
    norms = [np.linalg.norm(v) for v in vectors]
    print(f'For {mode}-vectors, the norm is {np.mean(norms):.2f} with std {np.std(norms):.2f}. Max absolute-value difference of {np.max(np.abs(vectors)):.2f}.')

# %% Run the patches
values = np.random.randn(*cheese_diff_values(0, main_label, hook).shape) * rand_magnitude
# Cast this to float32
values = values.astype(np.float32)
print(np.max(values).max())
for seed in range(5):
    run_seed(seed, hook, [-1], values_tup=(values, 'garbage'))

# It doesn't work, and destroys performance. In contrast, the cheese vector has a targeted and constrained effect on the network (when not transferring to other mazes), and does little when attempting transfer. This seems intriguing.

# %% Patch out each residual block
@interact
def run_label(seed=IntSlider(min=0, max=20, step=1, value=0), zero_target=Dropdown(options=labels, value='embedder.block2.res1.conv2_out')):
    venv = create_venv(num=1, start_level=seed, num_levels=1)
    patches = get_zero_patch(label=zero_target)
    fig, axs, info = compare_patched_vfields(venv, patches, hook, ax_size=5)
    # title the fig with label
    fig.suptitle(zero_target)
    plt.show()

# %% Generate random mouse observations and then mean-ablate
obs = maze.get_random_obs(50, spawn_cheese=False)
# Show a random observation
# plt.imshow(rearrange(obs[2], 'c h w -> h w c'))
# plt.show()

@interact 
def mean_ablate(seed=IntSlider(min=0, max=20, step=1, value=0), label=Dropdown(options=labels, value='embedder.block3.res2.resadd_out')):
    venv = create_venv(num=1, start_level=seed, num_levels=1)
    hook.run_with_input(obs)
    random_values = hook.get_value_by_label(label)
    patches = get_mean_patch(random_values, label=label) 
    fig, axs, info = compare_patched_vfields(venv, patches, hook, ax_size=5)
    # title the fig with label
    fig.suptitle(f'Mean patching layer {label}')
    # Ensure the title is close to the plots
    fig.subplots_adjust(top=1.05)
    plt.show() 


# %% Patching different layers
""" We chose the layer block2.res1.resadd_out because it seemed to have a strong effect on the vector field. Let's see what happens when we patch other layers. """

# NOTE conv_in0 doesn't have effect, but shouldn't that literally make agent not see cheese? And why don't all bottleneck layers completely change agent computation so that it doesn't see cheese, at least at the relevant square? 
# Actually you can't patch conv_in0, because it's not a parameter (it's an input)
@interact
def run_all_labels(seed=IntSlider(min=0, max=20, step=1, value=0), coeff=FloatSlider(min=-3, max=3, step=0.1, value=-1), label=Dropdown(options=labels)):
    fig, _, _ = plot_patched_vfields(seed, coeff, label, hook)
    plt.show()    
    print(f'Patching {label} layer')

# %% Try all patches at once 
@interact 
def run_all_patches(seed=IntSlider(min=0, max=20, step=1, value=0), coeff=FloatSlider(min=-1, max=1, step=0.025, value=-.05)):
    venv = get_cheese_venv_pair(seed) 
    patches = {}
    for label in labels:
        if label == 'fc_value_out': continue
        values = values_from_venv(venv, hook, label)
        patches.update(get_values_diff_patch(values=values, coeff=coeff, label=label))
        
    fig, _, _ = compare_patched_vfields(venv, patches, hook)
    plt.show()


# %% Check how patch transferability changes with cheese location 
GENERATE_NUM = 50 # Number of seeds to generate, if generate is True
SEARCH_NUM = 2 # Number of seeds to search for, if generate is False

def test_transfer(source_seed : int, col_translation : int = 0, row_translation : int = 0, generate : bool = False, target_index : int = 0):
    """ Visualize what happens if the patch is transferred to a maze with the cheese translated by the given amount. 
    
    Args:
        source_seed (int): The seed from which the patch was generated.
        col_translation (int): The number of columns to translate the cheese by.
        row_translation (int): The number of rows to translate the cheese by.
        generate (bool): Whether to modify existing mazes or search for existing ones.
        target_index (int): The index of the target maze to use, among the seeds generated or searched for. 
    """
    values = cheese_diff_values(source_seed, main_label, hook)
    cheese_location = maze.get_cheese_pos_from_seed(source_seed)

    assert cheese_location[0] < maze.WORLD_DIM - row_translation, f"Cheese is too close to the bottom for it to be translated by {row_translation}."
    assert cheese_location[1] < maze.WORLD_DIM - col_translation, f"Cheese is too close to the right for it to be translated by {col_translation}."

    if generate: 
        seeds, grids = maze.generate_mazes_with_cheese_at_location((cheese_location[0] , cheese_location[1]+col_translation), num_mazes = GENERATE_NUM, skip_seed=source_seed)
    else: 
        seeds = maze.get_mazes_with_cheese_at_location((cheese_location[0] , cheese_location[1]+col_translation), num_mazes=SEARCH_NUM, skip_seed = source_seed)

    if generate:  
        venv = maze.venv_from_grid(grid=grids[target_index])
        patches = get_values_diff_patch(values, -1, main_label)
        fig, _, _ = compare_patched_vfields(venv, patches, hook, render_padding=False)
    else:
        fig, _, _ = plot_patched_vfields(seeds[target_index], -1, main_label, hook, values=values)
    display(fig)
    print(f'The true cheese location is {cheese_location}. The new location is row {cheese_location[0] + row_translation}, column {cheese_location[1]+col_translation}. Rendered seed: {seeds[target_index]}, where the cheese was{"" if generate else " not"} moved to the target location.')

# %% Natural cheese_location target mazes 
# TODO is this the same -- are natural mazes first generated and _then_ cheese is placed? Or is cheese placed and then the maze built around it, or something else?

# Transfers to mazes with cheese at the same location, using SEARCH_NUM real seeds found via rejection sampling.
_ = interact(test_transfer, source_seed=IntSlider(min=0, max=20, step=1, value=0), col_translation=IntSlider(min=-5, max=5, step=1, value=0), row_translation=IntSlider(min=-5, max=5, step=1, value=0), generate=fixed(False), target_index=IntSlider(min=0, max=SEARCH_NUM-1, step=1, value=0))

# %% Synthetic transfer to same cheese locations
""" Most levels don't have cheese in the same spot. The above method is slow, because it rejection-samples levels until it finds one with cheese in the right spot. Let's try a synthetic transfer, where we find levels with an open spot at the appropriate location, and then move the cheese there. """
_ = interact(test_transfer, source_seed=IntSlider(min=0, max=20, step=1, value=0), col_translation=IntSlider(min=-5, max=5, step=1, value=0), row_translation=IntSlider(min=-5, max=5, step=1, value=0), generate=fixed(True), target_index=IntSlider(min=0, max=GENERATE_NUM-1, step=1, value=0))

# %% See if the cheese patch blinds the agent
@interact 
def compare_with_original(seed=IntSlider(min=0, max=20, step=1, value=0)):
    cheese_pair = get_cheese_venv_pair(seed, has_cheese_tup = (False, True))
    values = cheese_diff_values(seed, main_label, hook)
    patches = get_values_diff_patch(values, coeff=-1, label=main_label)
    fig, axs, _ = compare_patched_vfields(cheese_pair, patches, hook, render_padding=False, reuse_first=False) 
    plt.show()

# %%
