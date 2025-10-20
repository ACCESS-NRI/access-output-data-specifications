"""
Builds custom markdown tables for ACCESS-NRI ESM1.6 data spec dcos from the
schema defined in the ACCESS-NRI schema repo.
"""
import json
from json_ref_dict import materialize, RefDict
import pandas as pd

# Define the columns for the output tables and their formatted names
GLOBAL_COLS = {'title': 'Title', 'description': 'Description', 'type': 'Type', 'examples': 'Examples', 'rules': 'Rules'}
VARIABLE_COLS = {'title': 'Title', 'description': 'Description', 'type': 'Type', 'examples': 'Examples'}

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
    global_attrs = schema['properties']['global']['properties']
    variable_attrs = schema['properties']['variables']['patternProperties']['^.+$']['properties']

    # Build pandas tables out of the jsons
    global_df = pd.DataFrame.from_records(global_attrs).T
    variable_df = pd.DataFrame.from_records(variable_attrs).T

    # Sort dataframe alphabetically by attribute names
    global_df.sort_values('title', inplace=True, key=lambda col: col.str.lower())
    variable_df.sort_values('title', inplace=True, key=lambda col: col.str.lower())

    # Escape |s in regex patterns
    global_df['pattern'] = global_df['pattern'].str.replace('|', '\\|')

    # oneOf is a list of dicts {pattern: regex}, convert to a list of strings
    global_df['oneOf'] = global_df['oneOf'].apply(lambda x: [xi['pattern'] for xi in x] if isinstance(x, list) else x)

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
                            return start_str + join_str.join([str(li) for li in l]) + end_str
                        elif len(l) == 1:
                            # Turn single items into just that item
                            return l[0]
                        
                    # Empty string for empty lists or nans
                    return ""

                df[col_name] = df[col_name].apply(list2str)

    # Prefix these columns with some explanatory text first
    prefix_d = {"pattern": "Must match regex: ", "oneOf": "Must match one of these regex: ", "enum": "Must be one of the following: "}

    for key, prefix in prefix_d.items():
        global_df[key] = global_df[key].apply(lambda x: prefix + x if isinstance(x, str) else x)

    # Unify the pattern, oneOf, and enum columns
    global_df['rules'] = global_df['pattern'].fillna(global_df['oneOf']).fillna(global_df['enum'])

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
