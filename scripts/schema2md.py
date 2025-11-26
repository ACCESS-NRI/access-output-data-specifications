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

MAPPING_COLS = {
    "cmip7_compound_name": "CMIP7 Name",
    "cmip6_compound_name": "CMIP6 Name",
    "standard_name": "CF Standard Name",
    "units": "Units",
    "frequency": "Freq",
    "esm15_name": "ACCESS Name",
    "esm15_mapping": "Mapping",
}

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

    # Get the global and variable attributes
    global_attrs = schema["properties"]["global"]["properties"]
    variable_attrs = schema["properties"]["variables"]["patternProperties"]["^.+$"][
        "properties"
    ]

    # Build pandas tables out of the jsons
    global_df = pd.DataFrame.from_records(global_attrs).T
    variable_df = pd.DataFrame.from_records(variable_attrs).T

    # Add required as a column to both dfs
    def add_required(df, name):
        if "required" in schema["properties"][name]:
            required = schema["properties"][name]["required"]
        else:
            required = []

        df = df.assign(required=[row_name in required for row_name in df.index])

        # Convert True/False to Yes/No
        df["required"] = df["required"].replace({True: "Yes", False: "No"})

        return df

    global_df = add_required(global_df, "global")
    variable_df = add_required(variable_df, "variables")

    # Sort dataframe alphabetically by attribute names
    global_df.sort_values("title", inplace=True, key=lambda col: col.str.lower())
    variable_df.sort_values("title", inplace=True, key=lambda col: col.str.lower())

    # Escape |s in regex patterns
    global_df["pattern"] = global_df["pattern"].str.replace("|", "\\|")

    # oneOf is a list of dicts {pattern: regex}, convert to a list of strings
    global_df["oneOf"] = global_df["oneOf"].apply(
        lambda x: [xi["pattern"] for xi in x] if isinstance(x, list) else x
    )

    # Certain columns are lists, convert them to strings
    dot_point_lists = True
    for df in [global_df, variable_df]:
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
    prefix_d = {
        "pattern": "Must match regex: ",
        "oneOf": "Must match one of these regex: ",
        "enum": "Must be one of the following: ",
    }

    for key, prefix in prefix_d.items():
        global_df[key] = global_df[key].apply(
            lambda x: prefix + x if isinstance(x, str) else x
        )

    # Unify the pattern, oneOf, and enum columns
    global_df["rules"] = (
        global_df["pattern"].fillna(global_df["oneOf"]).fillna(global_df["enum"])
    )

    # Replace nans with empty strings
    global_df = global_df.fillna("")
    variable_df = variable_df.fillna("")

    # Filter and rename output columns
    global_final_df = global_df[GLOBAL_COLS.keys()].rename(columns=GLOBAL_COLS)
    variable_final_df = variable_df[VARIABLE_COLS.keys()].rename(columns=VARIABLE_COLS)

    # Format markdown table to files
    global_md_str = global_final_df.to_markdown(index=False, tablefmt="github")
    variable_md_str = variable_final_df.to_markdown(index=False, tablefmt="github")

    return global_md_str, variable_md_str


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

    # Load MOPPy mappings (presumably for CMIP6 ESM1.5?)
    moppy_mappings = {}

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
