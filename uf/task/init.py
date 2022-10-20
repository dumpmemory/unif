from ..third import tf
from ._base_ import Task


class Initialization(Task):
    """ Initialze the model, make it ready for inference. """

    def run(self, reinit_all, ignore_checkpoint):

        # build graph
        self.module._set_placeholders()
        _, self.module.tensors = self.module._parallel_forward(is_training=False)

        # init session
        if reinit_all or not self.module._session_built:
            self._init_session(ignore_checkpoint=ignore_checkpoint)

        # init uninitialized variables
        else:
            variables = []
            for var in self.module.global_variables:
                if var not in self.module._inited_vars:
                    variables.append(var)
            if variables:
                self._init_variables(variables, ignore_checkpoint=ignore_checkpoint)
            else:
                tf.logging.info(
                    "Global variables already initialized. To re-initialize all, "
                    "pass `reinit_all` to True."
                )
        self.module._session_mode = "infer"
