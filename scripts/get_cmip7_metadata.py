"""
Uses the CMIP7-Data-Request package to get the metadata for the Core CMIP7
variables.
"""
from data_request_api.content import dreq_content, dump_transformation
from data_request_api.query import data_request, dreq_query

def get_variables_list(priority='Core'):
    """
    Get a list of CMIP7 variable compound names for a given priority.

    Args:
        priority: The priority of the variables to get. Should be one of
            'Core', 'High', 'Medium', 'Low'
    Returns:
        A list of variables' CMIP7 compound names
    """
    content_dic = dump_transformation.get_transformed_content()
    DR = data_request.DataRequest.from_separated_inputs(**content_dic)
    variables = DR.find_variables_per_priority(priority)
    return [v.id for v in variables]

def get_variable_metadata(variable_list, use_dreq_version='v1.2.2.2'):
    """
    Get the metadata for the given list of CMIP7 variables.

    Args:
        variable_list: A list of CMIP7 variable compound names.
    Returns:
        A dictionary of metadata
    """
    # Load data request content
    dreq_content.retrieve(use_dreq_version)
    content = dreq_content.load(use_dreq_version)

    # Get metadata for variables
    return dreq_query.get_variables_metadata(
        content,
        use_dreq_version,
        compound_names=variable_list,
        verbose=False
    )
