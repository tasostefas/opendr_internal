#!/usr/bin/env python
# Copyright 2020-2022 OpenDR European Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os
import time
from sensor_msgs.msg import PointCloud as ROS_PointCloud
import rclpy
from rclpy.node import Node
from opendr_ros2_bridge import ROS2Bridge
from opendr.engine.datasets import DatasetIterator
from opendr.perception.object_detection_3d import KittiDataset, LabeledPointCloudsDatasetIterator


class PointCloudDatasetNode(Node):
    def __init__(
        self,
        dataset: DatasetIterator,
        output_point_cloud_topic="/opendr/dataset_point_cloud",
        data_fps=10,
    ):
        """
        Creates a ROS Node for publishing dataset point clouds
        """

        super().__init__('point_cloud_dataset_node')

        # Initialize the face detector
        self.dataset = dataset
        # Initialize OpenDR ROSBridge object
        self.bridge = ROS2Bridge()
        self.timer = self.create_timer(1.0 / data_fps, self.timer_callback)
        self.sample_index = 0

        if output_point_cloud_topic is not None:
            self.output_point_cloud_publisher = self.create_publisher(
                ROS_PointCloud, output_point_cloud_topic, 1
            )

    def timer_callback(self):

        point_cloud = self.dataset[self.sample_index % len(self.dataset)][0]  # Dataset should have a (PointCloud, Target) pair as elements

        self.get_logger().info("Publishing point_cloud [" + str(self.sample_index) + "]")
        message = self.bridge.to_ros_point_cloud(
            point_cloud, self.get_clock().now().to_msg()
        )
        self.output_point_cloud_publisher.publish(message)

        self.sample_index += 1

def main(
    args=None,
):
    rclpy.init(args=args)
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dataset_path", help="Path to a dataset. If does not exist, nano KITTI dataset will be downloaded there.",
                        type=str, default="image_raw")
    parser.add_argument("-ks", "--kitti_subsets_path", help="Path to kitti subsets. Used only if a KITTI dataset is downloaded",
                        type=str, default="../../src/opendr/perception/object_detection_3d/datasets/nano_kitti_subsets")
    args = parser.parse_args()

    dataset_path = args.dataset_path
    kitti_subsets_path = args.kitti_subsets_path

    if not os.path.exists(dataset_path):
        dataset_path = KittiDataset.download_nano_kitti(
            "KITTI", kitti_subsets_path=kitti_subsets_path,
            create_dir=True,
        ).path

    dataset = LabeledPointCloudsDatasetIterator(
        dataset_path + "/training/velodyne_reduced",
        dataset_path + "/training/label_2",
        dataset_path + "/training/calib",
    )

    dataset_node = PointCloudDatasetNode(dataset)

    rclpy.spin(dataset_node)

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    dataset_node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
