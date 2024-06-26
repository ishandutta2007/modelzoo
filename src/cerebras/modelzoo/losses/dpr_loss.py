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

from torch import nn

from cerebras.modelzoo.common.registry import registry


@registry.register_loss("DPRLoss")
class DPRLoss(nn.Module):
    def __init__(
        self,
    ):
        super(DPRLoss, self).__init__()
        self.loss_fn = nn.CrossEntropyLoss()

    def forward(self, scores, labels):
        loss = self.loss_fn(scores, labels)
        return loss
