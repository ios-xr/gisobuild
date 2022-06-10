# -----------------------------------------------------------------------------

""" Metadata validation helpers.

Copyright (c) 2022 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

        https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.


This module provides helper functions that do basic data and type
validation on dictionaries that can be used to populate dataclasses.

The APIs take a dataclass and a candidate data dictionary, and validate
that the data contained in the dictionary satisfies the type constraints
imposed by the dataclass. Two APIs are exposed:

- :func:`.validate`: just validates the data in the dict against the dataclass

- :func:`.create`: validates the data, and if successful, creates a dataclass
  instance populated with data from the dict.

If validation fails, an expection will be raised that inherits from
the :class:`ValidateError` defined in this module.

This module supports typechecking of the following types from the
:mod:`typing` package:

- :obj:`typing.Dict`

- :obj:`typing.List`

- :obj:`typing.Optional`

- :obj:`typing.Tuple`

- :obj:`typing.Union`

along with the following base python types:

- :class:`bool`

- :class:`int`

- :class:`str`

- :class:`enum.Enum`

and ``None`` for missing fields.

This module also supports parsing arbitrarily nested variations of the
above types.

When running with python 3.8 and above, this module also supports
the use of :obj:`typing.Literal`.

This module makes a disinction between optional fields and fields with
optional values:

- An optional field is one with a default value or default factory.
  If these aren't present in the input data, they're populated using the
  default (factory).

- A field with an optional value is one annotated with `Optional[..]` or
  `Union[None, ..]`. This simply allows the value `None` as a valid
  value for the field. If no default or default factory is set for a field
  and it's not present in the input data, an error is raised.

- A field can both be optional and have an optional value by having both
  an `Optional[..]` type definition and a default or default factory.

"""


__all__ = (
    "validate",
    "create",
    "info",
    "ValidateError",
    "ClassValidateError",
    "FieldValidateError",
    "CombinedValidateError",
    "MultiValidateError",
)


import collections
import contextlib
import copy
import dataclasses
import enum
import inspect
import sys
import textwrap
import typing
from typing import (
    cast,
    Any,
    Callable,
    Dict,
    FrozenSet,
    Generator,
    Iterable,
    List,
    NoReturn,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)


# Generic type variable used in the API.
T = TypeVar("T")
"""
Generic type variable used in the API.
"""

# Type alias for a type annotation type.
Annotation = Any


# There are a couple of mypy false positives, including:
# - type variables being used with isinstance()
# - access of default_factory attributes of dataclass fields
# - thinking that dataclasses.Field is subscriptable when it's not
# These have been marked with type: ignore until mypy fixes the bugs.


def get_origin(tp: Any) -> Any:
    """
    Get the origin type.

    Calls typing.get_origin() for python 3.8+.
    Similar implementation otherwise (invloving looking at dunder fields).

    """
    assert sys.version_info.major == 3
    if sys.version_info >= (3, 8):
        return typing.get_origin(tp)
    else:
        try:
            return tp.__origin__
        except AttributeError:
            return None


def get_args(tp: Any) -> Tuple[Any, ...]:
    """
    Get the origin type.

    Calls typing.get_args() for python 3.8+.
    Similar implementation otherwise (invloving looking at dunder fields).

    """
    assert sys.version_info.major == 3
    if sys.version_info >= (3, 8):
        return typing.get_args(tp)
    else:
        try:
            return typing.cast(Tuple[Any, ...], tp.__args__)
        except AttributeError:
            return ()


class ValidateError(Exception):
    """
    Exception raised when a validation error occurs.

    """

    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(f"Validation error: {msg}")


class ClassValidateError(ValidateError):
    """
    Exception Raised when a particular class fails validation.

    """

    def __init__(
        self,
        cls: Type[Any],
        msg: str,
        entry: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.cls = cls
        self.class_msg = msg
        self.entry = entry
        self.description = description

        if self.entry is not None:
            entry_str = f" (entry: {self.entry})"
        else:
            entry_str = ""

        if description is not None:
            desc = description
        else:
            desc = cast(str, getattr(self.cls, "__validate_description", None))
            if desc is None:
                desc = self.cls.__qualname__

        super().__init__(
            f"in class {desc}{entry_str}:\n{textwrap.indent(msg, '  ')}"
        )


class FieldValidateError(ClassValidateError):
    """
    Exception raised when a particular field fails validation.

    """

    def __init__(
        self,
        cls: Type[Any],
        field: str,
        msg: str,
        entry: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.field = field
        self.field_msg = msg
        super().__init__(
            cls, f"invalid field '{field}' - {msg}", entry, description
        )


class CombinedValidateError(ClassValidateError):
    """
    Exception raised after validation failures with `collect_errors` set.

    """

    def __init__(
        self,
        cls: Type[Any],
        errors: Sequence[ClassValidateError],
        entry: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.errors = errors

        assert (
            errors
        ), "CombinedValidateError must be raised with a non-empty error list"

        super().__init__(
            cls, self.to_msg(), entry=entry, description=description
        )

    def to_msg(self) -> str:
        """
        Convert error to message.

        """
        msg_lines: List[str] = []
        for error in self.errors:
            if isinstance(error, ClassValidateError):
                msg_lines.append(error.class_msg)
            else:
                assert False, (
                    "CombinedValidateError can only be created from "
                    "ClassValidateError instances"
                )

        return "\n".join(msg_lines)


class MultiValidateError(ValidateError):
    """
    Exception to group together multiple ValidateErrors.

    """

    def __init__(self, errors: Sequence[ValidateError]):
        self.errors = errors
        assert (
            errors
        ), "MultiValidateError must be raised with a non-empty error list"

        super().__init__(self.to_msg())

    def to_msg(self) -> str:
        """
        Convert error to message.
        """
        return "\n".join(str(e) for e in self.errors)


def info(
    description: Optional[str] = None,
    id_field: Optional[str] = None,
) -> Callable[[Type[T]], Type[T]]:
    """
    Validate info decorator.

    Use to add validation info to a dataclass.

    :param description:
        Description of the dataclass type (used for error messages).

    :param id_field:
        The name of the field to be used as an identifier for
        a dataclass instance (used fo error messages).

    """

    def decorator(cls: Type[Any]) -> Type[Any]:
        # pylint: disable=protected-access
        cls.__validate_description = description
        cls.__validate_id_field = id_field
        # pylint: enable=protected-access
        return cls

    return decorator


@dataclasses.dataclass
class _Flags:
    """
    Flags for data validation.

    The supported flags are:
        sanitize:
            Flag indicating whether to mutate the data to ensure it's
            valid for dataclass creation.
            This includes:
                - setting missing optional fields data, with the
                value `None`
                - doing any changes policed by other flags.

        relaxed_base_types:
            Flag indicating whether relaxed type-checking for base types
            (int, str, and bool) should be used.
            If this is set:
                - ints may be implicitly cast to strings
                (e.g. 123 is a valid int)
                - strings may be implicitly cast to ints
                (e.g. "123" is a valid int)
                - 0, 1, "0", and "1" are acceptable bools.
            This is useful when incoming data is in formats that don't
            explicitly differentiate between the two, e.g. YAML.

        collect_errors:
            Flag indicating whether exceptions should be raised immediately
            upon finding an error, or whether to collect as many failures
            as possible into a single exception.

            If this is set, as many errors as possible are found, collected
            together and raised in a single :exc:`ValidateError`.
            Otherwise, as soon as an errors is found a :exc:`ValidateError`
            is raised and the validation halts.

    """

    sanitize: bool = False
    relaxed_base_types: bool = False
    collect_errors: bool = True


class _Context:
    """
    Context for data validation.

    :ivar dataclass:
        The dataclass being used for validation.

    :ivar flags:
        A :class:`.Flags` instance use for validation options.

    :ivar description:
        The description passed in by the user when calling :func:`.validate`
        or :func:`.create`.

    :ivar entry:
        The "name" of the data being validated.
        This is derived from the :func:`.info` annotation on a dataclass,
        and the data passed in - it is the value of the `id_field` field.

    :ivar errors:
        Current list of errors. Used if the :attr:`.Flags.collect_errors`
        flag is set.

    """

    def __init__(
        self,
        dataclass: Type[Any],
        flags: _Flags,
        description: Optional[str] = None,
    ):
        self.dataclass = dataclass
        self.flags = flags
        self.description = description
        self.entry = None
        self.errors: List[ClassValidateError] = []

    def raise_class_validate_error(self, msg: str) -> NoReturn:
        """
        Raise a :exc:`ClassValidateError` with the instance context.

        """
        raise ClassValidateError(
            self.dataclass, msg, self.entry, self.description
        )

    def raise_field_validate_error(
        self, field_name: str, msg: str
    ) -> NoReturn:
        """
        Raise a :exr:`FieldValidateError` with the instance context.

        """
        raise FieldValidateError(
            self.dataclass, field_name, msg, self.entry, self.description
        )

    def raise_caught_errors(self) -> None:
        """
        If any caught errors, raise a :exc:`ValidateError`.

        This exception will contain information about all the errors
        caught using the :func:`catch_validate_errors` context manager.

        """
        # If there are no errors, just return immediately.
        if not self.errors:
            return

        raise CombinedValidateError(
            self.dataclass, self.errors, self.entry, self.description
        )

    def set_entry_name(self, data: Dict[str, Any]) -> None:
        """
        Set the entry name based on the stored dataclass.

        Uses the `id_field` name set in the :func:`info` decorator.

        """
        id_field = getattr(self.dataclass, "__validate_id_field", None)
        if id_field is not None:
            self.entry = data.get(id_field, "<unknown>")

    @contextlib.contextmanager
    def catch_validate_errors(self) -> Generator[None, None, None]:
        """
        Context manager that catches and stores :exc:`ValidateError`s.

        """
        try:
            yield
        except ClassValidateError as e:
            self.errors.append(e)

    @contextlib.contextmanager
    def maybe_catch_validate_errors(self) -> Generator[None, None, None]:
        """
        Context manager to catch errors based on the `collect_errors` flag.

        If the flag is set, this catches and stores :exc:`ValidateError`s.
        Otherwise, those errors are not caught and bubble up as normal.

        """
        if self.flags.collect_errors:
            with self.catch_validate_errors():
                yield
        else:
            yield


def _get_type_string(type_: Any) -> str:
    """
    Helper function to get a display string for a type annotation.

    :param type_:
        Type annotation to get a display string for.

    :return:
        Display string for the type.

    """
    # This is basically just to differentiate classes, for which
    # __qualname__ is a good display string, versus type annotations
    # (e.g. Union) which don't have that attribute.
    if inspect.isclass(type_):
        return str(type_.__qualname__)

    else:
        return str(type_)


def _get_value_string(val: Any) -> str:
    """
    Helper function to get a display string for a value.

    :param val:
        Value to get a display string for.

    :return:
        Display string for the value.

    """
    if isinstance(val, str):
        # If val is a string, put it in quotes for clarity.
        val_str = f"'{val}'"

    elif isinstance(val, enum.Enum):
        # Get the value string for the enum value.
        val_str = _get_value_string(val.value)

    else:
        # Just use the default string representation.
        val_str = str(val)

    # Cap the maximum length at 60 (pretty arbitrary limit), and if
    # truncated add "...".
    # If the value was a string, add the final quote back on!
    if len(val_str) > 60:
        if isinstance(val, str):
            val_str = val_str[:57] + "...'"
        else:
            val_str = val_str[:58] + "..."

    return val_str


# Individual type-checker functions.
# These all take in data of a arbitrary type, and:
#  - if the data is valid for the type, coerce it into the expected type
#    and return it.
#  - if the data is not valid for the type, raise an error.
#
# If the data being validated has structure (e.g. a dict, list etc...) the
# checker should call `_check_type` on each element of the structure.


def _check_dict(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Dict[Any, Any]:
    if not isinstance(value, dict):
        ctx.raise_field_validate_error(
            name,
            f"should be a dict, got {_get_type_string(type(value))} instead",
        )

    dict_types = get_args(expected_type)
    key_type, value_type = dict_types
    return {
        _check_type(f"keys of {name}", k, key_type, ctx): _check_type(
            f"{name}[{k!r}]", v, value_type, ctx
        )
        for k, v in value.items()
    }


def _check_list(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> List[Any]:
    if not isinstance(value, list):
        ctx.raise_field_validate_error(
            name,
            f"should be a list, got {_get_type_string(type(value))} instead",
        )

    list_types = get_args(expected_type)
    value_type = list_types[0] if list_types else Any
    return [
        _check_type(f"{name}[{i}]", v, value_type, ctx)
        for i, v in enumerate(value)
    ]


def _check_set_common(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Iterable[Any]:
    if not isinstance(value, (frozenset, list, tuple, set)):
        ctx.raise_field_validate_error(
            name,
            f"should be a set (or list), got "
            f"{_get_type_string(type(value))} instead",
        )

    set_types = get_args(expected_type)
    set_type = set_types[0] if set_types else Any
    item_counts = collections.Counter(
        _check_type(f"{name}[{i}]", v, set_type, ctx)
        for i, v in enumerate(value)
    )

    for item, count in item_counts.items():
        if count > 1:
            ctx.raise_field_validate_error(
                name,
                f"should have no duplicate items, "
                f"found {_get_value_string(item)} {count} times",
            )

    return item_counts


def _check_set(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Set[Any]:
    return set(_check_set_common(name, value, expected_type, ctx))


def _check_frozen_set(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> FrozenSet[Any]:
    return frozenset(_check_set_common(name, value, expected_type, ctx))


def _check_tuple(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        ctx.raise_field_validate_error(
            name,
            f"should be a tuple (or list), got "
            f"{_get_type_string(type(value))} instead",
        )

    tuple_types = get_args(expected_type)

    # Three options for validating tuples:
    #   - plain tuple or Tuple : return as-is.
    #   - Tuple[x, ...]        : treat it just like a list.
    #   - Tuple[x, y] etc...   : zip through the types and the entries
    #                            checking the type for each one.
    if not tuple_types:
        return tuple(value)

    elif len(tuple_types) == 2 and tuple_types[1] == Ellipsis:
        value_type = tuple_types[0]
        return tuple(
            _check_type(f"{name}[{i}]", v, value_type, ctx)
            for i, v in enumerate(value)
        )

    else:
        # If there's only one type specified, the user probably meant to
        # use an ellpisis.
        if len(tuple_types) == 1:
            did_you_mean = (
                f" (did you mean "
                f"Tuple[{_get_type_string(tuple_types[0])}, ...]?)"
            )
        else:
            did_you_mean = ""

        if len(value) != len(tuple_types):
            ctx.raise_field_validate_error(
                name,
                f"tuple should contain {len(tuple_types)} elements, "
                f"got {len(value)} instead{did_you_mean}",
            )

        return tuple(
            _check_type(f"{name}[{i}]", entry_value, entry_type, ctx)
            for (i, (entry_value, entry_type)) in enumerate(
                zip(value, tuple_types)
            )
        )


def _check_enum(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Any:
    try:
        value = expected_type(value)
    except ValueError:
        possible_values = "\n - ".join(
            _get_value_string(e) for e in expected_type
        )
        ctx.raise_field_validate_error(
            name,
            f"got invalid value {_get_value_string(value)}, "
            f"must be one of:\n - {possible_values}",
        )

    return value


def _check_union(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Any:
    union_params = get_args(expected_type)

    # Pylint false positive - can't access NoneType.
    # pylint: disable=unidiomatic-typecheck
    if len(union_params) == 2 and type(None) in union_params:
        # Effectively an 'Optional' type.
        # Special case this to give better error messages, since it should
        # be either exactly None, or an instance of the given type.
        if value is None:
            return value

        # If a value is present, check it's the right type.
        if union_params[0] is type(None):
            val_type = union_params[1]
        else:
            val_type = union_params[0]

        return _check_type_internal(name, value, val_type, ctx)

    else:
        # Otherwise, iterate through the possible types.
        errors = []
        for type_ in union_params:
            try:
                return _check_type_internal(name, value, type_, ctx)
            except FieldValidateError as e:
                errors.append(e)

    # pylint: enable=unidiomatic-typecheck

    possible_types = ", ".join(_get_type_string(t) for t in union_params)
    errs = "\n".join(
        # Some faffy extra indenting for list items.
        textwrap.indent(f"- {_get_type_string(t)}: {str(e)}", "    ")[2:]
        for (t, e) in zip(union_params, errors)
    )
    ctx.raise_field_validate_error(
        name,
        f"type must be one of ({possible_types}), none matched:\n{errs}",
    )


_ORIGIN_TYPE_CHECKERS = {
    dict: _check_dict,
    Dict: _check_dict,
    frozenset: _check_frozen_set,
    FrozenSet: _check_frozen_set,
    list: _check_list,
    List: _check_list,
    tuple: _check_tuple,
    Tuple: _check_tuple,
    set: _check_set,
    Set: _check_set,
    Union: _check_union,
}


if sys.version_info >= (3, 8):

    def _check_literal(
        name: str, value: Any, expected_type: Annotation, ctx: _Context
    ) -> Any:
        if value not in get_args(expected_type):
            possible_values = "\n - ".join(
                _get_value_string(v) for v in get_args(expected_type)
            )
            ctx.raise_field_validate_error(
                name,
                f"got invalid value {_get_value_string(value)}, "
                f"must be one of:\n - {possible_values}",
            )

        return value

    _ORIGIN_TYPE_CHECKERS[typing.Literal] = _check_literal


def _check_dataclass(
    name: str, value: Any, expected_type: Type[T], ctx: _Context
) -> T:
    if not isinstance(value, dict):
        ctx.raise_field_validate_error(
            name,
            f"should be a dict, got {_get_type_string(type(value))} instead",
        )

    sub_ctx = _Context(expected_type, ctx.flags, None)
    try:
        return typing.cast(T, _validate(value, sub_ctx))
    except ValidateError as e:
        ctx.raise_field_validate_error(name, str(e))


def _check_base(
    name: str, value: Any, expected_type: Type[T], ctx: _Context
) -> T:
    if isinstance(value, expected_type):
        new_value: Any = value

    elif expected_type in (str, int, bool) and ctx.flags.relaxed_base_types:
        # If the relaxed base types flag is set, check if the value should be
        # implicitly cast.
        error = False
        if isinstance(value, str) and expected_type is int:
            try:
                new_value = int(value)
            except ValueError:
                error = True

        elif isinstance(value, int) and expected_type is str:
            try:
                new_value = str(value)
            except ValueError:
                error = True

        elif isinstance(value, str) and expected_type is bool:
            if value == "0":
                new_value = False
            elif value == "1":
                new_value = True
            else:
                error = True

        elif isinstance(value, int) and expected_type is bool:
            if value == 0:
                new_value = False
            elif value == 1:
                new_value = True
            else:
                error = True

        else:
            error = True

        if error:
            ctx.raise_field_validate_error(
                name,
                f"type must be {_get_type_string(expected_type)}, "
                f"got {_get_type_string(type(value))} instead. "
                f"Tried implicit conversion but value "
                f"{_get_value_string(value)} could not be converted",
            )

    else:
        ctx.raise_field_validate_error(
            name,
            f"type must be {_get_type_string(expected_type)}, "
            f"got {_get_type_string(type(value))} instead",
        )

    return typing.cast(T, new_value)


def _check_type_internal(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Any:
    """
    Check that the given value matches the expected type.

    """
    if expected_type is Any:
        # No further checking required.
        return value

    if isinstance(expected_type, TypeVar):
        # No further type checking.
        return value

    origin_type = get_origin(expected_type)
    if origin_type is not None:
        checker_fn = _ORIGIN_TYPE_CHECKERS.get(origin_type)
        if checker_fn is not None:
            new_value = checker_fn(name, value, expected_type, ctx)
        else:
            new_value = _check_type_internal(name, value, origin_type, ctx)

    elif isinstance(expected_type, enum.EnumMeta):
        new_value = _check_enum(name, value, expected_type, ctx)

    elif dataclasses.is_dataclass(expected_type):
        new_value = _check_dataclass(name, value, expected_type, ctx)

    elif inspect.isclass(expected_type):
        new_value = _check_base(name, value, expected_type, ctx)

    else:
        # The annotation is something unsupported.
        # Print the annotation verbatim rather than prettifying
        assert (
            False
        ), f"Unsupported type check for field {name}: {expected_type}"

    if ctx.flags.sanitize:
        return new_value

    return value


def _check_type(
    name: str, value: Any, expected_type: Annotation, ctx: _Context
) -> Any:
    """
    Check that the given value matches the expected type.

    Maybe catches any raised errors base on the context flags.

    """
    with ctx.maybe_catch_validate_errors():
        return _check_type_internal(name, value, expected_type, ctx)


def _type_can_be_none(type_: Type[Any]) -> bool:
    """
    Check if a type can have the value None.

    """
    if type_ is Any:
        return True

    if type_ is type(None):
        return True

    origin = get_origin(type_)
    if origin is Union:
        return any(_type_can_be_none(sub_type) for sub_type in get_args(type_))

    return False


def _field_can_be_missing(field: "dataclasses.Field[Any]") -> bool:
    """
    Check if a dataclass field is allowed to be missing from the input.

    The type annotation is in quotes because of a conflict between mypy running
    at python version 3.9 and insisting on the type being specified, but the
    runtime environment being >= python 3.6 not being able to handle it.  By
    putting it in quotes only mypy picks up on it.

    """
    return (
        field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING  # type: ignore
    )


def _validate(raw_data: Dict[str, Any], ctx: _Context) -> Any:
    """
    Validate the given data is compatible with the dataclass definition.

    Internal implementation function.

    :param dataclass:
        Dataclass type.

    :param data:
        Data to validate against the dataclass.
        This may be mutated if the sanitize option is set.

    :param ctx:
        Context for the validation operation.
        See :class:`_Context` for more details.

    """
    # Python field variable names can't take hyphens yet metadata might include
    # them. Sanitise the raw input keys by replacing hyphens with underscores.
    data = {k.replace("-", "_"): v for k, v in raw_data.items()}

    # Set the entry name in the context.
    ctx.set_entry_name(data)

    # Find the expected and actual fields.
    # Only care about fields required for dataclass initialization.
    fields = [f for f in dataclasses.fields(ctx.dataclass) if f.init]
    actual_field_names = set(data.keys())

    # Check that only expected fields are specified.
    # Use a list to keep the ordering for error messages messages.
    expected_field_names = [f.name for f in fields if f.init]
    unexpected_fields = actual_field_names - set(expected_field_names)
    if unexpected_fields:
        with ctx.maybe_catch_validate_errors():
            # Catch errors to allow per-field checks to still happen.
            ctx.raise_class_validate_error(
                "invalid field names:\n - {}\nvalid fields are:\n - {}".format(
                    "\n - ".join(unexpected_fields),
                    # Re-extract the fields to get them in a
                    # deterministic order.
                    "\n - ".join(expected_field_names),
                )
            )

    # Check that all required fields are present.
    required_fields = set(
        f.name for f in fields if not _field_can_be_missing(f)
    )
    missing_fields = set(required_fields) - actual_field_names
    if missing_fields:
        with ctx.maybe_catch_validate_errors():
            # Catch errors to allow per-field checks to still happen.
            ctx.raise_class_validate_error(
                "missing required fields:\n - {}".format(
                    "\n - ".join(missing_fields)
                )
            )

    # Check all fields have valid values.
    try:
        type_hints = typing.get_type_hints(ctx.dataclass)
    except NameError as e:
        raise AssertionError("Unsupported annotation - expecting type") from e

    for field_name in data.keys():
        if field_name in type_hints:
            new_value = _check_type(
                field_name,
                data[field_name],
                type_hints[field_name],
                ctx,
            )
            if ctx.flags.sanitize:
                data[field_name] = new_value

    # If errors have been collected, make sure they're raised just before
    # the end of validation to allow as many to be found as possible, and for
    # any final sanitizing to be done.
    if ctx.flags.collect_errors:
        ctx.raise_caught_errors()

    # If the sanitize flag is set, add in any missing optional fields
    # with either their default values, or None if no default is set.
    # If any required fields are missing, will have had an error raised
    # before now, so can just add to all missing fields.
    if ctx.flags.sanitize:
        for field in fields:
            if field.name not in data:
                if field.default is not dataclasses.MISSING:
                    data[field.name] = field.default

                elif field.default_factory is not dataclasses.MISSING:  # type: ignore
                    data[field.name] = field.default_factory()

                else:
                    data[field.name] = None

        # Create the dataclass instance.
        return ctx.dataclass(**data)

    return None


def validate(
    dataclass: Type[Any],
    data: Dict[str, Any],
    description: Optional[str] = None,
    relaxed_base_types: bool = False,
    collect_errors: bool = True,
) -> None:
    """
    Validate the given data is compatible with the given dataclass definition.

    :param dataclass:
        Dataclass type.

    :param description:
        Description of the dataclass type (to be used in error messages).

    :param data:
        Data to validate against the dataclass.

    :param relaxed_base_types:
        Flag indicating whether relaxed type-checking for base types
        (int, str, and bool) should be used.

        If this is set:

          - ints may be implicitly cast to strings (e.g. 123 is a valid str)

          - strings may be implicitly cast to ints (e.g. "123" is a valid int)

          - certain ints and strings may be implicitly cast to bools:

            - 0 and "0" evaluate to False

            - 1 and "1" evaluate to True

            - other ints and strings cannot be implicitly cast

        This is useful when incoming data is in formats that don't
        explicitly differentiate between types, e.g. YAML.

    :param collect_errors:
        Flag indicating whether exceptions should be raised immediately
        upon finding an error, or whether to collect as many failures
        as possible into a single exception.

        If this is set, as many errors as possible are found, collected
        together and raised in a single :exc:`ValidateError`.
        Otherwise, as soon as an errors is found a :exc:`ValidateError`
        is raised and the validation halts.

    :raises:
        :exc:`ValidateError` if the data fails validation.

    """
    # If the given data isn't a dict, can't go very far!
    if not isinstance(data, dict):
        raise ValidateError(
            f"data input must be a dict, got a "
            f"{type(data).__qualname__} instead"
        )

    flags = _Flags(
        relaxed_base_types=relaxed_base_types, collect_errors=collect_errors
    )
    ctx = _Context(dataclass, flags, description=description)
    _validate(data, ctx)


def create(
    dataclass: Type[T],
    data: Dict[str, Any],
    description: Optional[str] = None,
    relaxed_base_types: bool = False,
    collect_errors: bool = True,
) -> T:
    """
    Validate the given data, and if valid, create a dataclass instance.

    Validates the data as per the :func:`validate` call.
    If no exceptions are raised, creates a dataclass instance with
    the given data and returns it.

    :param dataclass:
        Dataclass type.

    :param data:
        Data to validate against the dataclass, and use for dataclass
        instantiation if successful.

    This function first calls the :func:`validate` function, with the sanitize
    flag set to True.
    Any further options passed to this function will also be passed to
    the :func:`validate` function.

    :return:
        An instance of the dataclass type passed in.

    :raises:
        :exc:`ValidateError` if the data fails validation.

    """
    # If the given data isn't a dict, can't go very far!
    if not isinstance(data, dict):
        raise ValidateError(
            f"data input must be a dict, got a "
            f"{type(data).__qualname__} instead"
        )

    flags = _Flags(
        sanitize=True,
        relaxed_base_types=relaxed_base_types,
        collect_errors=collect_errors,
    )
    ctx = _Context(dataclass, flags, description=description)

    # Take a copy of the data to ensure the original isn't mutated.
    data_copy = copy.deepcopy(data)
    return _validate(data_copy, ctx)  # type: ignore
