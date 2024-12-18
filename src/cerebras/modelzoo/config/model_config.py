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

from typing import ClassVar

from cerebras.modelzoo.registry import registry

from .named_config import NamedConfig
from .utils import create_config_class


class ModelConfig(NamedConfig):
    discriminator: ClassVar[str] = "name"

    @property
    def __model_cls__(self):
        return registry.get_model_class(self.discriminator_value)

    def __call__(self, **kwargs):
        if self.__orig_class__ is None:
            return create_config_class(self.__model_cls__).model_validate(
                self
            )()
        return super().__call__(**kwargs)
