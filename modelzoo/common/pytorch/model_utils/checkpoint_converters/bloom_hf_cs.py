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

import logging
import math
import re
from typing import Tuple

import torch

from modelzoo.common.pytorch.model_utils.checkpoint_converters.base_converter import (
    BaseCheckpointConverter_HF_CS,
    BaseConfigConverter,
    BaseConfigConverter_HF_CS,
    ConfigConversionError,
    ConversionRule,
    EquivalentSubkey,
    FormatVersions,
)


class Converter_Bloom_Attention_HF_CS17(BaseCheckpointConverter_HF_CS):
    def __init__(self,):
        self.rules = [
            ConversionRule(
                [
                    EquivalentSubkey("dense", "proj_output_dense_layer"),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("query_key_value", "proj_q_dense_layer"),
                    "\.(?:weight|bias)",
                ],
                action=self.qkv_converter,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("query_key_value", "proj_k_dense_layer"),
                    "\.(?:weight|bias)",
                ],
                action=self.assert_already_converted,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("query_key_value", "proj_v_dense_layer"),
                    "\.(?:weight|bias)",
                ],
                action=self.assert_already_converted,
            ),
        ]

    def qkv_converter(
        self,
        old_key,
        new_key,
        old_state_dict,
        new_state_dict,
        from_index,
        action_fn_args,
    ):
        if from_index == 0:
            self.qkv_converter_hf_to_cs17(
                old_key, new_key, old_state_dict, new_state_dict, action_fn_args
            )
        else:
            self.qkv_converter_cs17_to_hf(
                old_key, new_key, old_state_dict, new_state_dict, action_fn_args
            )

    def qkv_converter_hf_to_cs17(
        self, old_key, new_key, old_state_dict, new_state_dict, action_fn_args
    ):
        # HF represents Q, K, and V in a packed format. We need to unpack the
        # weight and bias tensor for CS format.
        q_key = new_key
        k_key = re.sub("\.proj_q_dense_layer\.", ".proj_k_dense_layer.", q_key)
        v_key = re.sub("\.proj_q_dense_layer\.", ".proj_v_dense_layer.", q_key)
        num_heads = action_fn_args["configs"][1]["model"]["num_heads"]
        hidden_size = action_fn_args["configs"][1]["model"]["hidden_size"]

        if new_key.endswith(".bias"):
            reshaped = old_state_dict[old_key].view(
                num_heads, 3, hidden_size // num_heads
            )
            new_state_dict[q_key] = reshaped[:, 0, :].reshape(hidden_size)
            new_state_dict[k_key] = reshaped[:, 1, :].reshape(hidden_size)
            new_state_dict[v_key] = reshaped[:, 2, :].reshape(hidden_size)
        elif new_key.endswith(".weight"):
            reshaped = old_state_dict[old_key].view(
                num_heads, 3, hidden_size // num_heads, hidden_size
            )
            new_state_dict[q_key] = reshaped[:, 0, :, :].reshape(
                hidden_size, hidden_size
            )
            new_state_dict[k_key] = reshaped[:, 1, :, :].reshape(
                hidden_size, hidden_size
            )
            new_state_dict[v_key] = reshaped[:, 2, :, :].reshape(
                hidden_size, hidden_size
            )
        else:
            raise ValueError("Invalid key after conversion: {}".format(new_key))

    def qkv_converter_cs17_to_hf(
        self, old_key, new_key, old_state_dict, new_state_dict, action_fn_args
    ):
        # HF represents Q, K, and V in a packed format.
        q_key = old_key
        k_key = re.sub("\.proj_q_dense_layer\.", ".proj_k_dense_layer.", q_key)
        v_key = re.sub("\.proj_q_dense_layer\.", ".proj_v_dense_layer.", q_key)

        assert (
            k_key in old_state_dict
        ), "Expected the following key to exist! {}".format(k_key)
        assert (
            v_key in old_state_dict
        ), "Expected the following key to exist! {}".format(v_key)

        num_heads = action_fn_args["configs"][1]["model"]["num_heads"]
        hidden_size = action_fn_args["configs"][1]["model"]["hidden_size"]

        expand_dim = [
            num_heads,
            1,
            hidden_size // num_heads,
        ]
        shrink_dim = [hidden_size * 3]
        if new_key.endswith(".weight"):
            expand_dim += [
                hidden_size,
            ]
            shrink_dim += [
                hidden_size,
            ]

        new_state_dict[new_key] = torch.cat(
            (
                old_state_dict[q_key].view(*expand_dim),
                old_state_dict[k_key].view(*expand_dim),
                old_state_dict[v_key].view(*expand_dim),
            ),
            dim=1,
        ).view(*shrink_dim)

    def assert_already_converted(
        self,
        old_key,
        new_key,
        old_state_dict,
        new_state_dict,
        from_index,
        action_fn_args,
    ):
        if from_index == 0:
            # We should never hit this case as this key should have been matched
            # already
            assert False, "Invalid key: {}".format(old_key)
        else:
            # When we convert from CS -> HF, the proj_q_dense_layer should also handle
            # conversion of proj_k_dense_layer and proj_v_dense_layer since HF
            # represents these three layers in a packed format. We simply need
            # to test that the key containing the packed format has already
            # been converted.
            assert (
                new_key in new_state_dict
            ), "Key should've been already converted: {} -> {}".format(
                old_key, new_key
            )

    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.7"))

    @staticmethod
    def get_config_converter_class() -> BaseConfigConverter:
        return None


class Converter_BloomModel_HF_CS17(BaseCheckpointConverter_HF_CS):
    def __init__(self):
        super().__init__()
        self.rules = [
            ConversionRule(
                [
                    EquivalentSubkey(
                        "word_embeddings", "embedding_layer.word_embeddings"
                    ),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey(
                        "word_embeddings_layernorm", "embedding_ln_f"
                    ),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("h", "transformer_decoder.layers"),
                    "\.\d+\.",
                    EquivalentSubkey("self_attention.", "self_attn."),
                    Converter_Bloom_Attention_HF_CS17(),
                ],
                action=None,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("h", "transformer_decoder.layers"),
                    "\.\d+\.",
                    EquivalentSubkey("input_layernorm", "norm1"),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("h", "transformer_decoder.layers"),
                    "\.\d+\.",
                    EquivalentSubkey("post_attention_layernorm", "norm3"),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("h", "transformer_decoder.layers"),
                    "\.\d+\.",
                    EquivalentSubkey(
                        "mlp.dense_h_to_4h", "ffn.ffn.0.linear_layer"
                    ),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("h", "transformer_decoder.layers"),
                    "\.\d+\.",
                    EquivalentSubkey(
                        "mlp.dense_4h_to_h", "ffn.ffn.1.linear_layer"
                    ),
                    "\.(?:weight|bias)",
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("ln_f", "transformer_decoder.norm"),
                    "\.(?:weight|bias)",
                ],
                action=self.replace_final_norm,
            ),
            ConversionRule(["lm_head\.(?:weight|bias)"], exists="right"),
            ConversionRule(["ln_f\.(?:weight|bias)"], exists="right"),
            ConversionRule(["relative_pe_helper\.slopes",], exists="right"),
        ]

    def replace_final_norm(
        self,
        old_key,
        new_key,
        old_state_dict,
        new_state_dict,
        from_index,
        action_fn_args,
    ):
        new_state_dict[new_key] = old_state_dict[old_key]
        # CS 1.7 has both "ln_f" and "transformer_decoder.norm"
        # we need to copy the original ("ln_f") too:
        if from_index == 0:
            ln_f_key = re.sub("transformer_decoder\.norm\.", "ln_f.", new_key)
            new_state_dict[ln_f_key] = old_state_dict[old_key]

    @staticmethod
    def get_alibi_slopes(n):
        def get_slopes_power_of_2(n):
            start = 2 ** (-(2 ** -(math.log2(n) - 3)))
            ratio = start
            return [start * ratio ** i for i in range(n)]

        if math.log2(n).is_integer():
            slopes_list = get_slopes_power_of_2(
                n
            )  # In the paper, we only train models that have 2^a heads for some a. This function has
        else:  # some good properties that only occur when the input is a power of 2. To maintain that even
            closest_power_of_2 = 2 ** math.floor(
                math.log2(n)
            )  # when the number of heads is not a power of 2, we use this workaround.
            slopes_list = (
                get_slopes_power_of_2(closest_power_of_2)
                + Converter_BloomModel_HF_CS17.get_alibi_slopes(
                    2 * closest_power_of_2
                )[0::2][: n - closest_power_of_2]
            )
        return torch.tensor(slopes_list).unsqueeze(-1)

    def pre_model_convert(
        self,
        old_state_dict,
        new_state_dict,
        configs,
        from_index,
        drop_unmatched_keys,
    ):
        if from_index == 0:
            logging.warning(
                "{} GPT2 backbone has a language model head (lm_head) "
                "while {} BloomModel does not. Initializing lm_head to default.".format(
                    self.formats()[1], self.formats()[0]
                )
            )
        # Manually tie weights
        if from_index == 1 and configs[1]["model"]["share_embedding_weights"]:
            if (
                old_state_dict.get("embedding_layer.word_embeddings.weight", 0)
                is None
            ):
                old_state_dict[
                    "embedding_layer.word_embeddings.weight"
                ] = old_state_dict["lm_head.weight"]

    def post_model_convert(
        self,
        old_state_dict,
        new_state_dict,
        configs,
        from_index,
        drop_unmatched_keys,
    ):
        if from_index == 0:
            # We are converting from HF GPT2Model (which is headless) -> CS GPT2LMHeadModel
            # We need to create 'lm_head' and init to default values
            hf_config = configs[0]
            cs_config = configs[1]
            use_bias_in_output = cs_config["model"].get(
                "use_bias_in_output", False
            )
            vocab_size = cs_config["model"]["vocab_size"]
            embed_dim = cs_config["model"]["hidden_size"]
            if hf_config["tie_word_embeddings"]:
                lm_head_weight = old_state_dict['word_embeddings.weight']
            else:
                lm_head_weight = torch.zeros((vocab_size, embed_dim))
                lm_head_weight.normal_(mean=0.0, std=0.02)
            new_state_dict["lm_head.weight"] = lm_head_weight
            if use_bias_in_output:
                lm_head_bias = torch.zeros(vocab_size)
                new_state_dict["lm_head.bias"] = lm_head_bias
            new_state_dict[
                "relative_pe_helper.slopes"
            ] = Converter_BloomModel_HF_CS17.get_alibi_slopes(
                cs_config["model"]["num_heads"]
            )

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.7"))

    @classmethod
    def converter_note(cls) -> str:
        return (
            "{} BloomModel <-> {} GPT2LMHeadModel\n"
            "The HF model doesn't contain a language model head while the CS "
            "one does. When converting to CS, the exported checkpoint will "
            "contain a language model head initialized to default random values"
            ". When converting to HF, the language model head will be dropped."
        ).format(cls.formats()[0], cls.formats()[1])

    @staticmethod
    def get_config_converter_class() -> BaseConfigConverter:
        return ConfigConverter_BloomModel_HF_CS17


class Converter_BloomModel_HF_CS19(Converter_BloomModel_HF_CS17):
    def __init__(self):
        super().__init__()
        self.rules = [
            # Catch checkpoints from Pytorch 2.0 API
            ConversionRule([Converter_BloomModel_HF_CS17(),], action=None,),
            # Catch checkpoints from depricated PyTorchBaseModel
            ConversionRule(
                [
                    EquivalentSubkey("", "model."),
                    Converter_BloomModel_HF_CS17(),
                ],
                action=None,
            ),
        ]

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.9"))

    @classmethod
    def converter_note(cls) -> str:
        return (
            "{} BloomModel <-> {} GPT2LMHeadModel\n"
            "The HF model doesn't contain a language model head while the CS "
            "one does. When converting to CS, the exported checkpoint will "
            "contain a language model head initialized to default random values"
            ". When converting to HF, the language model head will be dropped."
        ).format(cls.formats()[0], cls.formats()[1])

    @staticmethod
    def get_config_converter_class() -> BaseConfigConverter:
        return ConfigConverter_BloomModel_HF_CS19


class ConfigConverter_BloomModel_HF_CS17(BaseConfigConverter_HF_CS):
    def __init__(self):
        super().__init__()
        self.rules = [
            # Embedding
            ConversionRule(["vocab_size"], action=self.replaceKey),
            ConversionRule(
                ["position_embedding_type"],
                exists="right",
                action=BaseConfigConverter.assert_factory_fn(1, "alibi"),
            ),
            ConversionRule(
                ["use_position_embedding"],
                exists="right",
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                ["embedding_dropout_rate"],
                action=BaseConfigConverter.assert_factory_fn(1, 0.0),
            ),
            ConversionRule(
                [
                    EquivalentSubkey(
                        "tie_word_embeddings", "share_embedding_weights"
                    )
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                ["embedding_layer_norm"],
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            # Decoder Block
            ConversionRule(["hidden_size"], action=self.replaceKey,),
            ConversionRule(
                [EquivalentSubkey("n_head", "num_heads")],
                action=self.replaceKey,
            ),
            ConversionRule(
                [EquivalentSubkey("n_layer", "num_hidden_layers")],
                action=self.replaceKey,
            ),
            ConversionRule(
                ["max_position_embeddings"], exists="right", action=None,
            ),
            ConversionRule(
                ["attention_type"],
                action=BaseConfigConverter.assert_factory_fn(
                    1, "scaled_dot_product"
                ),
            ),
            ConversionRule(
                ["attention_module"],
                action=BaseConfigConverter.assert_factory_fn(
                    1, "aiayn_attention"
                ),
            ),
            ConversionRule(
                ["attention_inner_dim"], action=self.assert_attention_inner_dim,
            ),
            ConversionRule(
                ["use_rms_norm"],
                action=BaseConfigConverter.assert_factory_fn(1, False),
            ),
            ConversionRule(
                ["use_projection_bias_in_attention"],
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                ["use_ffn_bias_in_attention"],
                exists="right",
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                ["use_ffn_bias"],
                exists="right",
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                ["filter_size"], exists="right", action=self.assert_filter_size,
            ),
            ConversionRule(
                ["nonlinearity"],
                action=BaseConfigConverter.assert_factory_fn(1, "gelu"),
            ),
            ConversionRule(
                ["apply_residual_connection_post_layernorm"],
                action=BaseConfigConverter.assert_factory_fn(0, False),
            ),
            ConversionRule(
                ["norm_first"],
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                [
                    EquivalentSubkey(
                        "attention_dropout", "attention_dropout_rate"
                    )
                ],
                action=self.replaceKey,
            ),
            ConversionRule(
                [EquivalentSubkey("hidden_dropout", "dropout_rate")],
                action=self.replaceKey,
            ),
            ConversionRule(["layer_norm_epsilon"], action=self.replaceKey,),
            ConversionRule(
                ["use_bias_in_output"],
                action=BaseConfigConverter.assert_factory_fn(1, False),
            ),
            ConversionRule(["initializer_range"], action=self.replaceKey),
            ConversionRule(
                ["fixed_sparse_attention"],
                action=BaseConfigConverter.assert_factory_fn(1, None),
            ),
            ConversionRule(
                ["norm_first"],
                action=BaseConfigConverter.assert_factory_fn(1, True),
            ),
            ConversionRule(
                ["use_ff_layer1_dropout"],
                action=BaseConfigConverter.assert_factory_fn(1, False),
            ),
            ConversionRule(
                ["scale_attn_by_inverse_layer_idx"],
                action=BaseConfigConverter.assert_factory_fn(0, False),
            ),
            ConversionRule(
                ["reorder_and_upcast_attn"],
                action=BaseConfigConverter.assert_factory_fn(0, False),
            ),
            ConversionRule(
                ["alibi_trainable_slopes"],
                action=BaseConfigConverter.assert_factory_fn(1, False),
            ),
        ]

    def assert_filter_size(
        self,
        old_key,
        new_key,
        old_state_dict,
        new_state_dict,
        from_index,
        action_fn_args,
    ):
        if old_state_dict[old_key] != 4 * old_state_dict["hidden_size"]:
            raise ConfigConversionError(
                "HF model only supports filter_size = 4 * hidden_size"
            )

    def assert_attention_inner_dim(
        self,
        old_key,
        new_key,
        old_state_dict,
        new_state_dict,
        from_index,
        action_fn_args,
    ):
        if (
            old_state_dict[old_key] is not None
            and old_state_dict[old_key] != old_state_dict["hidden_size"]
        ):
            raise ConfigConversionError(
                "HF model only supports attention_inner_dim = hidden_size"
            )

    def pre_config_convert(
        self, config, from_index,
    ):
        config = super().pre_config_convert(config, from_index)

        defaults = [
            {"tie_word_embeddings": True,},
            {"share_embedding_weights": True, "embedding_layer_norm": False},
        ]

        # Apply defaults
        for key in defaults[from_index]:
            if key not in config:
                config[key] = defaults[from_index][key]

        if from_index == 1:
            if "embedding_dropout_rate" not in config:
                config["embedding_dropout_rate"] = config["dropout_rate"]
            if "attention_dropout_rate" not in config:
                config["attention_dropout_rate"] = config["dropout_rate"]
        return config

    def post_config_convert(
        self,
        original_config,
        old_config,
        new_config,
        from_index,
        drop_unmatched_keys,
    ):
        if from_index == 0:
            new_config["position_embedding_type"] = "alibi"
            new_config["use_ffn_bias_in_attention"] = True
            new_config["use_projection_bias_in_attention"] = True
            new_config["use_ffn_bias"] = True
            new_config["use_bias_in_output"] = False
            new_config["attention_type"] = "scaled_dot_product"
            new_config["embedding_layer_norm"] = True
            new_config["filter_size"] = 4 * new_config["hidden_size"]

        return super().post_config_convert(
            original_config,
            old_config,
            new_config,
            from_index,
            drop_unmatched_keys,
        )

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.7"))


class ConfigConverter_BloomModel_HF_CS19(ConfigConverter_BloomModel_HF_CS17):
    def __init__(self):
        super().__init__()

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.9"))


class Converter_BloomLMHeadModel_HF_CS17(BaseCheckpointConverter_HF_CS):
    def __init__(self):
        super().__init__()
        self.rules = [
            ConversionRule(
                ["lm_head\.(?:weight|bias)"], action=self.replaceKey,
            ),
            ConversionRule(
                [
                    EquivalentSubkey("transformer.", ""),
                    Converter_BloomModel_HF_CS17(),
                ],
                action=None,
            ),
        ]

    def pre_model_convert(
        self,
        old_state_dict,
        new_state_dict,
        configs,
        from_index,
        drop_unmatched_keys,
    ):
        # Manually tie weights
        if from_index == 1 and configs[1]["model"]["share_embedding_weights"]:
            if (
                old_state_dict.get("embedding_layer.word_embeddings.weight", 0)
                is None
            ):
                old_state_dict[
                    "embedding_layer.word_embeddings.weight"
                ] = old_state_dict["lm_head.weight"]

    def post_model_convert(
        self,
        old_state_dict,
        new_state_dict,
        configs,
        from_index,
        drop_unmatched_keys,
    ):
        if from_index == 0:
            cs_config = configs[1]
            new_state_dict[
                "relative_pe_helper.slopes"
            ] = Converter_BloomModel_HF_CS17.get_alibi_slopes(
                cs_config["model"]["num_heads"]
            )

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.7"))

    @classmethod
    def converter_note(cls) -> str:
        return "{} BloomForCausalLM <-> {} GPT2LMHeadModel (configured as bloom)".format(
            cls.formats()[0], cls.formats()[1]
        )

    @staticmethod
    def get_config_converter_class() -> BaseConfigConverter:
        return ConfigConverter_BloomModel_HF_CS17


class Converter_BloomLMHeadModel_HF_CS19(BaseCheckpointConverter_HF_CS):
    def __init__(self):
        super().__init__()
        self.rules = [
            # Catch checkpoints from Pytorch 2.0 API
            ConversionRule(
                [Converter_BloomLMHeadModel_HF_CS17(),], action=None,
            ),
            # Catch checkpoints from depricated PyTorchBaseModel
            ConversionRule(
                [
                    EquivalentSubkey("", "model."),
                    Converter_BloomLMHeadModel_HF_CS17(),
                ],
                action=None,
            ),
        ]

    def post_model_convert(
        self,
        old_state_dict,
        new_state_dict,
        configs,
        from_index,
        drop_unmatched_keys,
    ):
        if from_index == 0:
            cs_config = configs[1]
            new_state_dict[
                "relative_pe_helper.slopes"
            ] = Converter_BloomModel_HF_CS17.get_alibi_slopes(
                cs_config["model"]["num_heads"]
            )

    @staticmethod
    def formats() -> Tuple[FormatVersions, FormatVersions]:
        return (FormatVersions("hf"), FormatVersions("cs-1.9"))

    @classmethod
    def converter_note(cls) -> str:
        return "{} BloomForCausalLM <-> {} GPT2LMHeadModel (configured as bloom)".format(
            cls.formats()[0], cls.formats()[1]
        )

    @staticmethod
    def get_config_converter_class() -> BaseConfigConverter:
        return ConfigConverter_BloomModel_HF_CS19