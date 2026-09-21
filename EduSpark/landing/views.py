from django.shortcuts import render


def index(request):
    """Render the single-page landing site."""
    return render(request, 'landing/index.html')
