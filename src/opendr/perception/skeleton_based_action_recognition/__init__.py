from opendr.perception.skeleton_based_action_recognition.continual_stgcn_learner import CoSTGCNLearner
from opendr.perception.skeleton_based_action_recognition.spatio_temporal_gcn_learner import (
    SpatioTemporalGCNLearner,
)
from opendr.perception.skeleton_based_action_recognition.progressive_spatio_temporal_gcn_learner import (
    ProgressiveSpatioTemporalGCNLearner,
)
from opendr.perception.skeleton_based_action_recognition.algorithm.datasets.ntu_gendata import (
    NTU60_CLASSES,
)
from opendr.perception.skeleton_based_action_recognition.algorithm.datasets.kinetics_gendata import (
    KINETICS400_CLASSES,
)

__all__ = [
    "CoSTGCNLearner",
    "SpatioTemporalGCNLearner",
    "ProgressiveSpatioTemporalGCNLearner",
    "NTU60_CLASSES",
    "KINETICS400_CLASSES",
]
