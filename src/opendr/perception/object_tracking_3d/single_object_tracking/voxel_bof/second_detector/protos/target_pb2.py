# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: second/protos/target.proto

import sys
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

from opendr.perception.object_tracking_3d.single_object_tracking.voxel_bof.second_detector.protos import (
    anchors_pb2 as second_dot_protos_dot_anchors__pb2,
)
from opendr.perception.object_tracking_3d.single_object_tracking.voxel_bof.second_detector.protos import (
    similarity_pb2 as second_dot_protos_dot_similarity__pb2,
)

_b = sys.version_info[0] < 3 and (lambda x: x) or (lambda x: x.encode("latin1"))

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor.FileDescriptor(
    name="second/protos/target.proto",
    package="second.protos",
    syntax="proto3",
    serialized_options=None,
    serialized_pb=_b(
        '\n\x1asecond/protos/target.proto\x12\rsecond.protos\x1a\x1bsecond/protos/anchors.pro' +
        'to\x1a\x1esecond/protos/similarity.proto"\x89\x02\n\x0eTargetAssigner\x12\x43\n\x11\x61ncho' +
        'r_generators\x18\x01 \x03(\x0b\x32(.second.protos.AnchorGeneratorCollection\x12 \n\x18sampl' +
        'e_positive_fraction\x18\x02 \x01(\x02\x12\x13\n\x0bsample_size\x18\x03 \x01(\r\x12\x16\n\x0euse' +
        '_rotate_iou\x18\x04 \x01(\x08\x12\x12\n\nclass_name\x18\x05 \x01(\t\x12O\n\x1cregion_similar' +
        'ity_calculator\x18\x06 \x01(\x0b\x32).second.protos.RegionSimilarityCalculatorb\x06proto3'
    ),
    dependencies=[
        second_dot_protos_dot_anchors__pb2.DESCRIPTOR,
        second_dot_protos_dot_similarity__pb2.DESCRIPTOR,
    ],
)


_TARGETASSIGNER = _descriptor.Descriptor(
    name="TargetAssigner",
    full_name="second.protos.TargetAssigner",
    filename=None,
    file=DESCRIPTOR,
    containing_type=None,
    fields=[
        _descriptor.FieldDescriptor(
            name="anchor_generators",
            full_name="second.protos.TargetAssigner.anchor_generators",
            index=0,
            number=1,
            type=11,
            cpp_type=10,
            label=3,
            has_default_value=False,
            default_value=[],
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
        _descriptor.FieldDescriptor(
            name="sample_positive_fraction",
            full_name="second.protos.TargetAssigner.sample_positive_fraction",
            index=1,
            number=2,
            type=2,
            cpp_type=6,
            label=1,
            has_default_value=False,
            default_value=float(0),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
        _descriptor.FieldDescriptor(
            name="sample_size",
            full_name="second.protos.TargetAssigner.sample_size",
            index=2,
            number=3,
            type=13,
            cpp_type=3,
            label=1,
            has_default_value=False,
            default_value=0,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
        _descriptor.FieldDescriptor(
            name="use_rotate_iou",
            full_name="second.protos.TargetAssigner.use_rotate_iou",
            index=3,
            number=4,
            type=8,
            cpp_type=7,
            label=1,
            has_default_value=False,
            default_value=False,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
        _descriptor.FieldDescriptor(
            name="class_name",
            full_name="second.protos.TargetAssigner.class_name",
            index=4,
            number=5,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=_b("").decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
        _descriptor.FieldDescriptor(
            name="region_similarity_calculator",
            full_name="second.protos.TargetAssigner.region_similarity_calculator",
            index=5,
            number=6,
            type=11,
            cpp_type=10,
            label=1,
            has_default_value=False,
            default_value=None,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
        ),
    ],
    extensions=[],
    nested_types=[],
    enum_types=[],
    serialized_options=None,
    is_extendable=False,
    syntax="proto3",
    extension_ranges=[],
    oneofs=[],
    serialized_start=107,
    serialized_end=372,
)

_TARGETASSIGNER.fields_by_name[
    "anchor_generators"
].message_type = second_dot_protos_dot_anchors__pb2._ANCHORGENERATORCOLLECTION
_TARGETASSIGNER.fields_by_name[
    "region_similarity_calculator"
].message_type = second_dot_protos_dot_similarity__pb2._REGIONSIMILARITYCALCULATOR
DESCRIPTOR.message_types_by_name["TargetAssigner"] = _TARGETASSIGNER
_sym_db.RegisterFileDescriptor(DESCRIPTOR)

TargetAssigner = _reflection.GeneratedProtocolMessageType(
    "TargetAssigner",
    (_message.Message,),
    dict(
        DESCRIPTOR=_TARGETASSIGNER,
        __module__="second.protos.target_pb2"
        # @@protoc_insertion_point(class_scope:second.protos.TargetAssigner)
    ),
)
_sym_db.RegisterMessage(TargetAssigner)


# @@protoc_insertion_point(module_scope)
