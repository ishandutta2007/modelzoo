# Copyright 2022 Cerebras Systems.
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

"""
Script that generates a dataset in tfrecords
format for GPT2Model.
"""
import argparse
import json
import logging
import os
import sys

import tensorflow as tf

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../../.."))
from modelzoo.common.input.utils import check_and_create_output_dirs
from modelzoo.common.tf.input.utils import create_int_feature
from modelzoo.transformers.data_processing.utils import count_total_documents
from modelzoo.transformers.tf.gpt2.input.data_processor_utils import (
    training_data_generator,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--metadata_files",
        type=str,
        required=True,
        help="path to text file containing a list of file names "
        "corresponding to the raw input documents to be "
        "processed and stored; can handle multiple metadata files "
        "separated by comma",
    )
    parser.add_argument(
        "--vocab_file", type=str, required=True, help="path to vocabulary"
    )
    parser.add_argument(
        "--encoder_file", type=str, required=True, help="path to BPE encoder"
    )
    parser.add_argument(
        "--max_seq_length",
        type=int,
        default=128,
        help="maximum sequence length. Defaults to 128.",
    )
    parser.add_argument(
        "--short_seq_prob",
        type=float,
        default=0.1,
        help="probability of creating sequences which are shorter "
        "than the maximum sequence length. Defaults to 0.1.",
    )
    parser.add_argument(
        "--add_special_tokens",
        type=bool,
        default=True,
        help="Add '<endoftext>' token at the end of each document. "
        "Defaults to True.",
    )
    parser.add_argument(
        "--overlap_size",
        type=int,
        default=None,
        help="overlap size for generating sequences from buffered data. "
        "Defaults to None, which sets the overlap to max_seq_len/4.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./tfrecords/",
        help="directory where TFRecords will be stored. "
        "Defaults to ./tfrecords/'.'",
    )
    parser.add_argument(
        "--num_output_files",
        type=int,
        default=10,
        help="number of files on disk to separate tfrecords into. "
        "Defaults to 10.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="examples",
        help="name of the dataset; i.e. prefix to use for TFRecord names. "
        "Defaults to 'examples'.",
    )

    parser.add_argument(
        "--seed", type=int, default=0, help="random seed. Defaults to 0.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    output_dir = args.output_dir
    check_and_create_output_dirs(output_dir, filetype="tfrecord")

    num_output_files = max(args.num_output_files, 1)
    output_files = [
        os.path.join(output_dir, f"{args.name}-{fidx+1}.tfrecords")
        for fidx in range(num_output_files)
    ]

    writers = []
    for output_file in output_files:
        writers.append(tf.io.TFRecordWriter(output_file))

    def _data_generator():
        return training_data_generator(
            args.metadata_files.split(','),
            args.vocab_file,
            args.encoder_file,
            args.max_seq_length,
            buffer_size=1e6,
            overlap_size=args.overlap_size,
            short_seq_prob=args.short_seq_prob,
            inverted_mask=False,
            add_special_tokens=args.add_special_tokens,
            eos_token="<|endoftext|>",
            pad_token="<|endoftext|>",
            seed=args.seed,
        )

    writer_index = 0
    total_written = 0
    features_dict = dict()

    tf.compat.v1.logging.info("Writing instances to output files...")
    for output_file in output_files:
        tf.compat.v1.logging.info(f"  {output_file}")

    for features, labels in _data_generator():
        features_dict["input_ids"] = create_int_feature(features["input_ids"])
        features_dict["input_mask"] = create_int_feature(features["input_mask"])
        features_dict["labels"] = create_int_feature(labels)
        tf_example = tf.train.Example(
            features=tf.train.Features(feature=features_dict)
        )

        writers[writer_index].write(tf_example.SerializeToString())
        writer_index = (writer_index + 1) % len(writers)

        total_written += 1
        if not total_written % 10000:
            tf.compat.v1.logging.info(f"{total_written} examples written...")

    for writer in writers:
        writer.close()

    # store arguments used for tfrecords
    # generation into a json file
    params = vars(args)
    params["n_examples"] = total_written
    params["n_docs"] = count_total_documents(args.metadata_files.split(','))
    json_params_file = os.path.join(output_dir, "data_params.json")
    with open(json_params_file, 'w') as _fout:
        json.dump(params, _fout)

    tf.compat.v1.logging.info(f"Done! Wrote total of {total_written} examples.")


if __name__ == "__main__":
    main()