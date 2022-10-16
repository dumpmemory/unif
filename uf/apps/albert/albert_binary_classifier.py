from .albert import ALBERTEncoder, ALBERTConfig, get_decay_power
from ..base.base_classifier import ClassifierModule
from ..bert.bert_binary_classifier import BERTBinaryClassifier
from ..base.base import BinaryClsDecoder
from ...token import WordPieceTokenizer
from ...third import tf


class ALBERTBinaryClassifier(BERTBinaryClassifier, ClassifierModule):
    """ Multi-label classifier on ALBERT. """
    _INFER_ATTRIBUTES = BERTBinaryClassifier._INFER_ATTRIBUTES

    def __init__(
        self,
        config_file,
        vocab_file,
        max_seq_length=128,
        label_size=None,
        label_weight=None,
        init_checkpoint=None,
        output_dir=None,
        gpu_ids=None,
        drop_pooler=False,
        do_lower_case=True,
        truncate_method="LIFO",
    ):
        self.__init_args__ = locals()
        super(ClassifierModule, self).__init__(init_checkpoint, output_dir, gpu_ids)

        self.batch_size = 0
        self.max_seq_length = max_seq_length
        self.label_size = label_size
        self.label_weight = label_weight
        self.truncate_method = truncate_method
        self._drop_pooler = drop_pooler
        self._id_to_label = None

        self.albert_config = ALBERTConfig.from_json_file(config_file)
        self.tokenizer = WordPieceTokenizer(vocab_file, do_lower_case)
        self.decay_power = get_decay_power(self.albert_config.num_hidden_layers)

        if "[CLS]" not in self.tokenizer.vocab:
            self.tokenizer.add("[CLS]")
            self.albert_config.vocab_size += 1
            tf.logging.info("Add necessary token `[CLS]` into vocabulary.")
        if "[SEP]" not in self.tokenizer.vocab:
            self.tokenizer.add("[SEP]")
            self.albert_config.vocab_size += 1
            tf.logging.info("Add necessary token `[SEP]` into vocabulary.")

    def _forward(self, is_training, split_placeholders, **kwargs):

        encoder = ALBERTEncoder(
            albert_config=self.albert_config,
            is_training=is_training,
            input_ids=split_placeholders["input_ids"],
            input_mask=split_placeholders["input_mask"],
            segment_ids=split_placeholders["segment_ids"],
            drop_pooler=self._drop_pooler,
            **kwargs,
        )
        encoder_output = encoder.get_pooled_output()
        decoder = BinaryClsDecoder(
            is_training=is_training,
            input_tensor=encoder_output,
            label_ids=split_placeholders["label_ids"],
            label_size=self.label_size,
            sample_weight=split_placeholders.get("sample_weight"),
            label_weight=self.label_weight,
            scope="cls/seq_relationship",
            **kwargs,
        )
        return decoder.get_forward_outputs()
