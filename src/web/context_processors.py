def homeowner(request):
    """Exposes is_homeowner so templates only link to the dashboard for users allowed to see it."""
    user = request.user
    return {'is_homeowner': user.is_authenticated and user.groups.filter(name='homeowner').exists()}
