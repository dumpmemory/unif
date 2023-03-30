import copy
import numpy as np

from .stockbert import StockBERTEncoder
from .._base_._base_classifier import ClsDecoder, ClassifierModule
from ..bert.bert import BERTConfig, get_decay_power
from ...third import tf
from ... import com


class StockBERTClassifier(ClassifierModule):
    """ Single-label classifier on Stock-BERT. """

    _INFER_ATTRIBUTES = {    # params whose value cannot be None in order to infer without training
        "max_seq_length": "An integer that defines max length of input time spots",
        "max_unit_length": "An integer that defines max length of input sub-prices",
        "init_checkpoint": "A string that directs to the checkpoint file used for initialization",
    }

    def __init__(
        self,
        config_file,
        max_seq_length=128,
        max_unit_length=60,
        label_size=None,
        init_checkpoint=None,
        output_dir=None,
        gpu_ids=None,
        drop_pooler=False,
        do_lower_case=True,
        truncate_method="LIFO",
    ):
        self.__init_args__ = locals()
        super(ClassifierModule, self).__init__(init_checkpoint, output_dir, gpu_ids)

        self.max_seq_length = max_seq_length
        self.max_unit_length = max_unit_length
        self.label_size = label_size
        self.truncate_method = truncate_method
        self._drop_pooler = drop_pooler

        self.bert_config = BERTConfig.from_json_file(config_file)
        self.decay_power = get_decay_power(self.bert_config.num_hidden_layers)

    def convert(self, X=None, y=None, sample_weight=None, X_tokenized=None, is_training=False, is_parallel=False):
        self._assert_legal(X, y, sample_weight, X_tokenized)

        assert X is None, "`%s` is a model with continuous input. `X` should be None. Use `X_tokenized` instead." % self.__class__.__name__
        if is_training:
            assert y is not None, "`y` can't be None."
        if is_parallel:
            assert self.label_size, "Can't parse data on multi-processing when `label_size` is None."

        n_inputs = None
        data = {}

        # convert X
        if X is not None or X_tokenized is not None:
            tokenized = False if X is not None else X_tokenized
            input_values, input_mask = self._convert_X(X_tokenized if tokenized else X, tokenized=tokenized)
            data["input_values"] = np.array(input_values, dtype=np.float32)
            data["input_mask"] = np.array(input_mask, dtype=np.int32)
            n_inputs = len(input_values)

            if n_inputs < self.batch_size:
                self.batch_size = max(n_inputs, len(self._gpu_ids))

        # convert y
        if y is not None:
            label_ids = self._convert_y(y)
            data["label_ids"] = np.array(label_ids, dtype=np.int32)

        # convert sample_weight
        if is_training or y is not None:
            sample_weight = self._convert_sample_weight(sample_weight, n_inputs)
            data["sample_weight"] = np.array(sample_weight, dtype=np.float32)

        return data

    def _convert_X(self, X_target, tokenized):

        # tokenize input texts
        segment_input_values = []
        for idx, sample in enumerate(X_target):
            try:
                segment_input_values.append(self._convert_x(sample))
            except Exception as e:
                raise ValueError(
                    "Wrong input format (%s): %s. An example: "
                    "`X_tokenized = [[[0.0023, -0.0001, 0.0015, ...], ...], "
                    "...]`" % (sample, e)
                )

        input_values = []
        input_mask = []
        for idx, segments in enumerate(segment_input_values):
            _input_values = []
            _input_mask = []

            com.truncate_segments([segments], self.max_seq_length - 1, truncate_method=self.truncate_method)
            for s_id, segment in enumerate(segments):
                assert len(segment) == self.max_unit_length, "`max_unit_length` must be equal to the input length of each time spot."
                _input_values.append(segment)
                _input_mask.append(1)

            # padding
            _input_mask.append(1)
            for _ in range(self.max_seq_length - 1 - len(_input_values)):
                _input_values.append([0] * self.max_unit_length)
                _input_mask.append(0)

            input_values.append(_input_values)
            input_mask.append(_input_mask)

        return input_values, input_mask

    def _convert_x(self, x):
        assert isinstance(x[0], list) and isinstance(x[0][0], float)
        return copy.deepcopy(x)

    def _convert_y(self, y):
        label_set = set(y)

        # automatically set `label_size`
        if self.label_size:
            assert len(label_set) <= self.label_size, "Number of unique `y`s exceeds `label_size`."
        else:
            self.label_size = len(label_set)

        # automatically set `id_to_label`
        if not self._id_to_label:
            self._id_to_label = list(label_set)
            try:
                # Allign if user inputs continual integers.
                # e.g. [2, 0, 1]
                self._id_to_label = list(sorted(self._id_to_label))
            except Exception:
                pass

        # automatically set `label_to_id` for prediction
        if not self._label_to_id:
            self._label_to_id = {label: index for index, label in enumerate(self._id_to_label)}

        label_ids = []
        for label in y:
            if label not in self._label_to_id:
                assert len(self._label_to_id) < self.label_size, "Number of unique labels exceeds `label_size`."
                self._label_to_id[label] = len(self._label_to_id)
                self._id_to_label.append(label)
            label_ids.append(self._label_to_id[label])
        return label_ids

    def _set_placeholders(self, **kwargs):
        self.placeholders = {
            "input_values": tf.placeholder(tf.float32, [None, self.max_seq_length - 1, self.max_unit_length], "input_values"),
            "input_mask": tf.placeholder(tf.int32, [None, self.max_seq_length], "input_mask"),
            "label_ids": tf.placeholder(tf.int32, [None], "label_ids"),
            "sample_weight": tf.placeholder(tf.float32, [None], "sample_weight"),
        }

    def _forward(self, is_training, placeholders, **kwargs):

        encoder = StockBERTEncoder(
            bert_config=self.bert_config,
            is_training=is_training,
            input_values=placeholders["input_values"],
            input_mask=placeholders["input_mask"],
            drop_pooler=self._drop_pooler,
            **kwargs,
        )
        encoder_output = encoder.get_pooled_output()
        decoder = ClsDecoder(
            is_training=is_training,
            input_tensor=encoder_output,
            label_ids=placeholders["label_ids"],
            label_size=self.label_size,
            sample_weight=placeholders.get("sample_weight"),
            scope="cls/seq_relationship",
            **kwargs,
        )
        train_loss, tensors = decoder.get_forward_outputs()
        return train_loss, tensors
