"""
Builds custom markdown tables for ACCESS-NRI ESM1.6 data spec dcos from the
schema defined in the ACCESS-NRI schema repo.
"""

from json_ref_dict import materialize, RefDict
import pandas as pd

from stashmasters import StashVar
from get_cmip7_metadata import get_variables_list, get_variable_metadata
from access_moppy.utilities import load_model_mappings

# Define the columns for the output tables and their formatted names
GLOBAL_COLS = {
    "title": "Title",
    "description": "Description",
    "examples": "Examples",
    "rules": "Rules",
    "required": "Required",
}
VARIABLE_COLS = {
    "title": "Title",
    "description": "Description",
    "type": "Type",
    "examples": "Examples",
}
TIME_COLS = {
    "title": "Title",
    "description": "Description",
    "type": "Type",
    "examples": "Examples",
}

MAPPING_COLS = {
    "cmip7_compound_name": "CMIP7 Name",
    "cmip6_compound_name": "CMIP6 Name",
    "standard_name": "CF Standard Name",
    "units": "Units",
    "frequency": "Freq",
    "esm15_name": "ACCESS Name",
    "esm15_mapping": "Mapping",
}


def process_subschema(subschema_dict, required, cols, dot_point_lists=True):
    # Build pandas tables out of the json
    df = pd.DataFrame.from_records(subschema_dict['properties']).T

    # Add required
    df = df.assign(required=["Yes" if row_name in required else "No" for row_name in df.index])

    # Escape |s in regex patterns
    try:
        df["pattern"] = df["pattern"].str.replace("|", "\\|")
    except KeyError:
        # Not every schema has 'pattern'
        pass

    # oneOf is a list of dicts {pattern: regex}, convert to a list of strings
    try:
        df["oneOf"] = df["oneOf"].apply(
            lambda x: [xi["pattern"] for xi in x] if isinstance(x, list) else x
        )
    except KeyError:
        # Not every schema has 'oneOf'
        pass

    # Certain columns are lists, convert them to strings
    for col_name in df.columns:
        # dtype for list columns is object so we need to go grab one to check
        col = df[col_name].dropna()
        contents = col.iloc[0]

        if isinstance(contents, list):
            if dot_point_lists:
                join_str = "</li><li>"
                start_str = "<ul><li>"
                end_str = "</li></ul>"
            else:
                join_str = ", "
                start_str = ""
                end_str = ""

            def list2str(l):
                if isinstance(l, list):
                    if len(l) > 1:
                        # Turn multi-item lists into dot point lists
                        return (
                            start_str
                            + join_str.join([str(li) for li in l])
                            + end_str
                        )
                    elif len(l) == 1:
                        # Turn single items into just that item
                        return l[0]
                    else:
                        # Empty string for empty lists
                        return ""

                # Otherwise just return the item as is
                return l

            df[col_name] = df[col_name].apply(list2str)

    # Prefix these columns with some explanatory text first
    # Then unify them into a new column "rules"
    prefix_d = {
        "pattern": "Must match regex: ",
        "oneOf": "Must match one of these regex: ",
        "enum": "Must be one of the following: ",
    }
    df["rules"] = pd.Series(index=df.index, name="pattern")
    for key, prefix in prefix_d.items():
        try:
            df[key] = df[key].apply(
                lambda x: prefix + x if isinstance(x, str) else x
            )
            df["rules"] = df["rules"].fillna(df[key])
        except KeyError:
            # Not every schema has 'pattern', 'oneOf', 'enum'
            pass

    # If "title" is missing fill it with the index
    df["title"] = df["title"].fillna(df.index.to_series())

    # If description is missing then use the const to give a description
    try:
        const_str = "Must have the value '{}'"
        extended_const = df["const"].map(lambda s: const_str.format(s), na_action="ignore")
        df["description"] = df["description"].fillna(extended_const)
    except KeyError:
        # Not every schema will have const
        pass

    # Sort dataframe alphabetically by attribute names
    df.sort_values("title", inplace=True, key=lambda col: col.str.lower())

    # Replace nans with empty strings
    df = df.fillna("")

    # Filter and rename output columns
    df = df[cols.keys()].rename(columns=cols)

    return df.to_markdown(index=False, tablefmt="github")


def schema2md(schema_url, dot_point_lists=True):
    """
    Acquire the schema from the URL and parse it into two markdown tables which
    are returned as strings.

    Args:
        schema_url: The url of the schema to parse into tables
        dot_point_lists: Whether to parse lists into dot points (True) or comma
            separated strings (False)
    Returns:
        global_md, variable_md: A tuple of strings of markdown for the global
            attributes table and the variable attributes table
    """
    # Get the schema as a json
    schema = materialize(RefDict(schema_url))

    # Process the global metadata    
    global_attrs = schema["properties"]["global"]
    global_required = global_attrs["required"]
    global_md_str = process_subschema(global_attrs, global_required, GLOBAL_COLS)

    # Process the generic variable metadata
    variable_attrs = schema["properties"]["variables"]
    variable_required = global_attrs["required"]
    variable_md_str = process_subschema(variable_attrs["patternProperties"]["^.+$"], variable_required, VARIABLE_COLS)

    # Process metadata for the time variable
    time_attrs =  variable_attrs["properties"]['time']
    time_required = variable_attrs["properties"]['time']['required']
    time_md_str = process_subschema(time_attrs, time_required, TIME_COLS)

    return global_md_str, variable_md_str, time_md_str


def _parse_mapping(map_d):
    if isinstance(map_d, dict):
        if 'type' in map_d and map_d['type'] == 'direct':
            return ""
        else:
            op = map_d["operation"]
            join_str = ", "
            if op == "multiply":
                join_str = " * "
                op = ""
            elif op == "add":
                join_str = " + "
                op = ""
            elif op == "subtract":
                join_str = " - "
                op = ""
        
            try:
                args = map_d["operands"]
            except KeyError:
                # Try 'args' instead of operands, sometimes these are numbers not strings
                args = map_d["args"]
            args = map(_parse_mapping, args)
            args = join_str.join(args)
            return f"{op}({args})"
    else:
        return str(map_d)


def access2cfname(esm_varname):
    """
    Convert ACCESS stash-like name to CF standard name.

    ACCESS names are sometimes like this:
    "fld_s02i204" - e.g. fld_{stash_code}
    "fld_s03i236_max" - e.g. fld_{stash_code}_{min/max}
    """
    try:
        stash_code = 'm01' + esm_varname.split('_')[1]

        stash_number = int(stash_code[4:6] + stash_code[7:10])
        sv = StashVar(stash_number, stashmaster="access-esm1.6")

        standard_name = sv.standard_name if sv.standard_name else sv.long_name.lower()
    except (ValueError, IndexError):
        # If name doesn't match expected format
        standard_name = 'unknown'

    return standard_name


def mapping2md():
    """
    Acquire mapping information from cached CMIP7 variable metadata and from
    ACCESS MOPPy mapping.

    Returns:
        mapping_md: A string of markdown/html representing the mappings table
    """
    # Load cmip7 core variable metadata
    cmip7_core_vars = get_variable_metadata(get_variables_list('Core'))

    # Augment CMIP7 metadata with MOPPy mappings
    for cmip7_var, cmip7_meta in cmip7_core_vars.items():
        _, cmip6_var = cmip7_meta['cmip6_compound_name'].split('.')

        # Get matching ACCESS variables using MOPPy
        moppy_mapping = load_model_mappings(cmip7_meta['cmip6_compound_name'])
        moppy_var_keys = list(moppy_mapping.keys())
        assert len(moppy_var_keys) <= 1, "MOPPy unexpected returned more than one key for {cmip6_var} - {moppy_var_keys}."

        if moppy_mapping == {}:
            esm_name = 'unknown'
            esm_mapping = 'unknown'
        else:
            # Add ACCESS variable to the dict
            try:
                esm_name = moppy_mapping[moppy_var_keys[0]]['model_variables']

                # Add standard name too if esm name is fld_{stashcode}
                if any(['fld_' in name for name in esm_name]):
                    esm_standard_names = map(access2cfname, esm_name)
                    esm_name = [f"{name} ({standard_name})" for name, standard_name in zip(esm_name, esm_standard_names)]
            except (KeyError, IndexError):
                esm_name = 'unknown'

            # Add the MOPPy mapping to the dict
            esm_mapping = _parse_mapping(moppy_mapping[moppy_var_keys[0]]['calculation'])

            # Remove parentheses from simple mappings (e.g. "(A+B)" -> "A+B")
            if len(esm_mapping) > 2 and esm_mapping[0] == '(' and esm_mapping[-1] == ')':
                esm_mapping = esm_mapping[1:-1]

        cmip7_core_vars[cmip7_var]['esm15_name'] = esm_name
        cmip7_core_vars[cmip7_var]['esm15_mapping'] = esm_mapping

    # Convert CMIP7 dict into pandas df
    df = pd.DataFrame.from_records(cmip7_core_vars).T

    # Convert lists to comma and newline separated strings
    for col_name in ['esm15_name']:
        df[col_name] = df[col_name].apply(lambda x: ',<br>'.join(x) if isinstance(x, list) else x)

    # Sort rows
    sort_order = ['cmip7_compound_name']
    for sort_by in sort_order[::-1]:
        df = df.sort_values(sort_by)

    final_df = df[MAPPING_COLS.keys()].rename(columns=MAPPING_COLS)
    return final_df.to_html(index=False, table_id="mapping", classes="display", escape=False)
