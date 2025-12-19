import logging
from typing import Optional

import jawa.attributes.bootstrap
import jawa.constants
from jawa.classloader import ClassLoader
from jawa.util.descriptor import method_descriptor

from burger.util import WalkerCallback, try_eval_lambda, walk_method

from .topping import Topping


class BlocksTopping(Topping):
    """Gets most available block types."""

    PROVIDES = ['identify.block.superclass', 'blocks']

    DEPENDS = [
        'identify.block.register',
        'identify.block.list',
        'identify.identifier',
        'language',
        'version.data',
        'version.is_flattened',
    ]

    @staticmethod
    def list_super_classes(class_name, superclass, classloader):
        super_classes = []
        this_super_class = class_name
        while this_super_class != superclass:
            try:
                this_super_class = classloader[this_super_class].super_.name.value
            except FileNotFoundError:
                break
            super_classes.append(this_super_class)
        return super_classes

    @staticmethod
    def act(aggregate, classloader: ClassLoader):
        BlocksTopping._process(aggregate, classloader)
        return

    @staticmethod
    def _process(aggregate, classloader: ClassLoader):
        # All of the registration happens in the list class in this version.

        # net/minecraft/world/level/block/Blocks
        blocks_class: str = aggregate['classes']['block.list']
        blocks_cf = classloader[blocks_class]
        # The first field in the list class is a block
        # (restricted to public fields as 23w40a has a different first field)
        superclass = next(
            blocks_cf.fields.find(f=lambda m: m.access_flags.acc_public)
        ).type.name
        cf = classloader[superclass]
        aggregate['classes']['block.superclass'] = superclass

        if 'block' in aggregate['language']:
            language = aggregate['language']['block']
        else:
            language = None

        def get_display_name_for_block_id(text_id: str) -> Optional[str]:
            lang_key = f'minecraft.{text_id}'
            if language is not None and lang_key in language:
                return language[lang_key]

        # 23w40a+ (1.20.3) has a references class that defines the IDs for some blocks
        references_class = aggregate['classes'].get('block.references')
        references_class_fields_to_block_ids = {}
        if references_class:
            # process the references class
            references_cf = classloader[references_class]
            for method in references_cf.methods.find(name='<clinit>'):
                block_id = None
                for ins in method.code.disassemble():
                    if ins.mnemonic == 'ldc':
                        block_id = ins.operands[0].string.value
                    if ins.mnemonic == 'putstatic':
                        field = ins.operands[0].name_and_type.name.value
                        references_class_fields_to_block_ids[field] = block_id

        # Figure out what the builder class is
        ctor = cf.methods.find_one(name='<init>')
        builder_class = ctor.args[0].name

        builder_cf = classloader[builder_class]
        # Sets hardness and resistance
        hardness_setter = builder_cf.methods.find_one(args='FF')
        # There's also one that sets both to the same value
        hardness_setter_2 = None
        for method in builder_cf.methods.find(args='F'):
            for ins in method.code.disassemble():
                if ins.mnemonic == 'invokevirtual':
                    const = ins.operands[0]
                    if (
                        const.name_and_type.name.value == hardness_setter.name.value
                        and const.name_and_type.descriptor.value
                        == hardness_setter.descriptor.value
                    ):
                        hardness_setter_2 = method
                        break
        assert hardness_setter_2 is not None
        # ... and one that sets them both to 0
        hardness_setter_3 = None
        for method in builder_cf.methods.find(args=''):
            for ins in method.code.disassemble():
                if ins.mnemonic == 'invokevirtual':
                    const = ins.operands[0]
                    if (
                        const.name_and_type.name.value == hardness_setter_2.name.value
                        and const.name_and_type.descriptor.value
                        == hardness_setter_2.descriptor.value
                    ):
                        hardness_setter_3 = method
                        break
        assert hardness_setter_3 is not None

        block_behavior_cf = classloader[
            'net/minecraft/world/level/block/state/BlockBehaviour'
        ]
        assert block_behavior_cf
        properties_cf = classloader[
            'net/minecraft/world/level/block/state/BlockBehaviour$Properties'
        ]
        assert properties_cf
        force_solid_on_setter = properties_cf.methods.find_one(name='forceSolidOn')
        assert force_solid_on_setter
        force_solid_off_setter = properties_cf.methods.find_one(name='forceSolidOff')
        assert force_solid_off_setter
        requires_correct_tool_for_drops_setter = properties_cf.methods.find_one(
            name='requiresCorrectToolForDrops'
        )
        assert requires_correct_tool_for_drops_setter
        friction_setter = properties_cf.methods.find_one(name='friction')
        assert friction_setter
        light_setter = properties_cf.methods.find_one(name='lightLevel')
        assert light_setter

        register_legacy_stair = blocks_cf.methods.find_one(
            name='registerLegacyStair',
            args='Ljava/lang/String;Lnet/minecraft/world/level/block/Block;',
        )
        assert register_legacy_stair
        stair_block_class = 'net/minecraft/world/level/block/StairBlock'
        assert classloader[stair_block_class]

        weathering_copper_blocks_class = (
            'net/minecraft/world/level/block/WeatheringCopperBlocks'
        )
        assert classloader[weathering_copper_blocks_class]

        blocks = aggregate.setdefault('blocks', {})
        block = blocks.setdefault('block', {})
        ordered_blocks = blocks.setdefault('ordered_blocks', [])
        block_fields = blocks.setdefault('block_fields', {})

        # Find the static block registration method
        method = blocks_cf.methods.find_one(name='<clinit>')

        class Walker(WalkerCallback):
            def __init__(self):
                self.cur_id = 0

            # unused
            def on_new(self, ins, const):
                raise NotImplementedError()
                class_name = const.name.value

                super_classes = BlocksTopping.list_super_classes(
                    class_name, superclass, classloader
                )

                return {'class': class_name, 'super': super_classes}

            def on_invoke(self, ins, const, obj, args):
                method_name = const.name_and_type.name.value
                method_desc = const.name_and_type.descriptor.value
                desc = method_descriptor(method_desc)

                print(len(desc.args), ins.mnemonic, const.class_.name.value, desc.args)

                if ins.mnemonic == 'invokestatic':
                    if const.class_.name.value == blocks_class:
                        if (
                            # most blocks have 2 args, but some (like air) have 3:
                            # public static final Block AIR = register(
                            #   "air",
                            #   AirBlock::new,
                            #   BlockBehaviour.Properties.of().replaceable().noCollission().noLootTable().air()
                            # );
                            len(desc.args) in {2, 3}
                            # In 23w40a+ (1.20.3) the first argument can also be a reference to a
                            # ResourceKey<Block> in the block references class. We have a check in
                            # on_get_field that makes the argument get converted to a block ID
                            # string so it can be handled the same.
                            and (
                                desc.args[0].name == 'java/lang/String'
                                or desc.args[0].name
                                == aggregate['classes'].get('resourcekey')
                            )
                            and (
                                desc.args[-1].name == superclass
                                or desc.args[-1].name == builder_class
                            )
                        ):
                            # Call to the static register method.
                            text_id = args[0]

                            current_block = args[-1]
                            if len(args) == 3 and isinstance(args[1], dict):
                                # args[1] is what we got from the invokedynamic (like the AirBlock::new)
                                current_block.update(args[1])

                            # if 'class' not in current_block:
                            current_block['text_id'] = text_id
                            current_block['numeric_id'] = self.cur_id
                            self.cur_id += 1
                            current_block['display_name'] = (
                                get_display_name_for_block_id(text_id)
                            )

                            if (
                                method_name == register_legacy_stair.name.value
                                and method_desc
                                == register_legacy_stair.descriptor.value
                            ):
                                current_block['class'] = stair_block_class

                            block[text_id] = current_block
                            ordered_blocks.append(text_id)
                            return current_block
                        elif (
                            len(desc.args) == 1
                            and desc.args[0].name == 'int'
                            and desc.returns.name == 'java/util/function/ToIntFunction'
                        ):
                            # 20w12a+: a method that takes a light level and returns a function
                            # that checks if the current block state has the lit state set,
                            # using light level 0 if not and the given light level if so.
                            # For our purposes, just simplify it to always be the given light level.
                            return args[0]
                        else:
                            # In 20w12a+ (1.16), some blocks (e.g. logs) use a separate method
                            # for initialization.  Call them.
                            sub_method = blocks_cf.methods.find_one(
                                name=method_name,
                                args=desc.args_descriptor,
                                returns=desc.returns_descriptor,
                            )
                            return walk_method(blocks_cf, sub_method, self, args)
                    elif const.class_.name.value == builder_class:
                        if (
                            len(desc.args) == 1
                            and desc.args[0].name == block_behavior_cf.this.name
                        ):
                            # ofLegacyCopy and ofFullCopy

                            copy = dict(args[0])
                            del copy['text_id']
                            del copy['numeric_id']
                            if 'class' in copy:
                                del copy['class']
                            if 'display_name' in copy:
                                del copy['display_name']
                            return copy
                        else:
                            return {}  # Append current block
                    elif const.class_.name.value == weathering_copper_blocks_class:
                        # public static final WeatheringCopperBlocks COPPER_BARS = WeatheringCopperBlocks.create(
                        #     "copper_bars",
                        #     Blocks::register,
                        #     IronBarsBlock::new,
                        #     WeatheringCopperBarsBlock::new,
                        #     p -> BlockBehaviour.Properties.of().requiresCorrectToolForDrops().strength(5.0F, 6.0F).sound(SoundType.COPPER).noOcclusion()
                        # );

                        print('args', args)
                        # exit()

                        text_id = args[0]

                        current_block = args[-1]
                        if len(args) == 3 and isinstance(args[1], dict):
                            # args[1] is what we got from the invokedynamic (like the AirBlock::new)
                            current_block.update(args[1])

                        # if 'class' not in current_block:
                        current_block['text_id'] = text_id
                        current_block['numeric_id'] = self.cur_id
                        self.cur_id += 1
                        current_block['display_name'] = get_display_name_for_block_id(
                            text_id
                        )

                        if (
                            method_name == register_legacy_stair.name.value
                            and method_desc == register_legacy_stair.descriptor.value
                        ):
                            current_block['class'] = stair_block_class

                        block[text_id] = current_block
                        ordered_blocks.append(text_id)
                        return current_block
                else:
                    if method_name == 'hasNext':
                        # We've reached the end of block registration
                        # (and have started iterating over registry keys)
                        raise StopIteration()

                    if (
                        method_name == hardness_setter.name.value
                        and method_desc == hardness_setter.descriptor.value
                    ):
                        obj['hardness'] = args[0]
                        obj['resistance'] = args[1]
                    elif (
                        method_name == hardness_setter_2.name.value
                        and method_desc == hardness_setter_2.descriptor.value
                    ):
                        obj['hardness'] = args[0]
                        obj['resistance'] = args[0]
                    elif (
                        method_name == hardness_setter_3.name.value
                        and method_desc == hardness_setter_3.descriptor.value
                    ):
                        obj['hardness'] = 0.0
                        obj['resistance'] = 0.0
                    elif (
                        method_name == light_setter.name.value
                        and method_desc == light_setter.descriptor.value
                    ):
                        if args[0] is not None:
                            obj['light'] = args[0]
                    elif (
                        method_name == force_solid_on_setter.name.value
                        and method_desc == force_solid_on_setter.descriptor.value
                    ):
                        obj['force_solid_on'] = True
                    elif (
                        method_name == force_solid_off_setter.name.value
                        and method_desc == force_solid_off_setter.descriptor.value
                    ):
                        obj['force_solid_off'] = True
                    elif (
                        method_name == requires_correct_tool_for_drops_setter.name.value
                        and method_desc
                        == requires_correct_tool_for_drops_setter.descriptor.value
                    ):
                        obj['requires_correct_tool_for_drops'] = True
                    elif (
                        method_name == friction_setter.name.value
                        and method_desc == friction_setter.descriptor.value
                    ):
                        obj['friction'] = args[0]
                    elif method_name == '<init>':
                        # Call to the constructor for the block
                        # The majority of blocks have a 1-arg constructor simply taking the builder.
                        # However, sand has public BlockSand(int color, Block.Builder builder), and
                        # signs (as of 1.15-pre1) have public BlockSign(Block.builder builder, WoodType type)
                        # (Prior to that 1.15-pre1, we were able to assume that the last argument was the builder)
                        # There are also cases of arg-less constructors, which we just ignore as they are presumably not blocks.
                        for idx, arg in enumerate(desc.args):
                            if arg.name == builder_class:
                                obj.update(args[idx])
                                break

                    if (
                        desc.returns.name == builder_class
                        or desc.returns.name == superclass
                    ):
                        return obj
                    elif desc.returns.name == aggregate['classes']['identifier']:
                        # Probably getting the air identifier from the registry
                        return 'air'
                    elif desc.returns.name != 'void':
                        return object()

            def on_get_field(self, ins, const, obj):
                if const.class_.name.value == superclass:
                    # Probably getting the static AIR resource location
                    return 'air'
                elif const.class_.name.value == references_class:
                    # get the block key from the references.Block class
                    if (
                        const.name_and_type.name.value
                        in references_class_fields_to_block_ids
                    ):
                        return references_class_fields_to_block_ids[
                            const.name_and_type.name.value
                        ]
                    else:
                        logging.debug(
                            f'Unknown field {const.name_and_type.name.value} in references class {references_class}'
                        )
                        return None
                elif const.class_.name.value == blocks_class:
                    if const.name_and_type.name.value in block_fields:
                        return block[block_fields[const.name_and_type.name.value]]
                    else:
                        # Can occur in 23w40a+ due to the additional private field
                        return None
                elif (
                    const.name_and_type.descriptor
                    == 'Ljava/util/function/ToIntFunction;'
                ):
                    # Light level lambda, used by candles.  Not something we
                    # can evaluate (it depends on the block state).
                    return None
                else:
                    return object()

            def on_put_field(self, ins, const, obj, value):
                print('PUT FIELD', const.name_and_type.name.value, value)
                if isinstance(value, dict):
                    field = const.name_and_type.name.value
                    value['field'] = field
                    block_fields[field] = value['text_id']

            def on_invokedynamic(self, ins, const, args):
                # 1.15-pre2 introduced a Supplier<BlockEntityType> parameter,
                # and while most blocks handled it in their own constructor,
                # chests put it directly in initialization.  We don't care about
                # the value (we get block entities in a different way), but
                # we still need to override this as the default implementation
                # raises an exception

                # 20w12a changed light levels to use a lambda, and we do
                # care about those.  The light level is a ToIntFunction<BlockState>.
                method_desc: str = const.name_and_type.descriptor.value
                desc = method_descriptor(method_desc)

                print('invokedynamic!', ins, const, args)

                if desc.returns.name in 'java/util/function/ToIntFunction':
                    # Try to invoke the function.
                    try:
                        args.append(object())  # The state that the lambda gets
                        return try_eval_lambda(ins, args, blocks_cf)
                    except Exception as ex:
                        logging.debug(f'Failed to call lambda for light data: {ex}')
                        return None
                elif desc.returns.name == 'java/util/function/BiFunction':
                    class_name = blocks_cf.constants.get(const.index - 1)
                    print('bifunction:', class_name)
                    try:
                        class_name = class_name.reference.class_.name.value
                        print('mrrp!!!!', class_name)
                    except AttributeError:
                        return object()
                # if it's a ::new then return {"class": class_name, "super": super_classes}
                elif desc.returns.name == 'java/util/function/Function':
                    # 228
                    bootstrap_method: jawa.attributes.bootstrap.BootstrapMethod = (
                        blocks_cf.bootstrap_methods[const.method_attr_index]
                    )

                    for arg_idx in bootstrap_method.bootstrap_args:
                        arg_value = blocks_cf.constants._pool[arg_idx]
                        print(' arg:', arg_idx, arg_value)

                    # print('method_data.args', method_data.args)
                    # print('method_data.name', method_data.name)
                    # print(
                    #     'method_data._descriptor_index', method_data._descriptor_index
                    # )
                    # print('method_data._name_index', method_data._name_index)

                    try:
                        # the args look like this:
                        # 0: <MethodType(index=8773,descriptor=<UTF8(index=221, value='(Ljava/lang/Object;)Ljava/lang/Object;'>))>
                        # 1: <MethodHandle(index=9504, reference=<MethodReference(index=9505,class_=<ConstantClass(index=9506, name=<UTF8(index=9507, value='net/minecraft/world/level/block/IronBarsBlock'>))>,name_and_type=<NameAndType(index=1075,name=<UTF8(index=5, value='<init>'>),descriptor=<UTF8(index=1076, value='(Lnet/minecraft/world/level/block/state/BlockBehaviour$Properties;)V'>))>)>)>
                        # 2: <MethodType(index=9512,descriptor=<UTF8(index=9513, value='(Lnet/minecraft/world/level/block/state/BlockBehaviour$Properties;)Lnet/minecraft/world/level/block/IronBarsBlock;'>))>

                        # line 22653

                        arg_1_idx = bootstrap_method.bootstrap_args[1]
                        arg_1_value: jawa.constants.MethodHandle = (
                            blocks_cf.constants._pool[arg_1_idx]
                        )
                        try:
                            synthetic_method = blocks_cf.constants._pool[
                                arg_1_value.reference.index
                            ]
                            print('synthetic_method', synthetic_method)
                        except Exception as e:
                            print('err', e)
                        class_name = arg_1_value.reference.class_.name.value
                        print('meow!!!!', class_name)
                    except AttributeError:
                        return object()

                    super_classes = BlocksTopping.list_super_classes(
                        class_name, superclass, classloader
                    )
                    return {'class': class_name, 'super': super_classes}
                else:
                    return object()

        walk_method(blocks_cf, method, Walker())
