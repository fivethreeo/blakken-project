"""
URL configuration for Meny project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from .views import auth, dish_detail, dish_list, index, job_results, menu_pages, move_dish

urlpatterns = [
    path('_nested_admin/', include('nested_admin.urls')),
    path('admin/', admin.site.urls),
    path('internal/auth/', auth, name='auth'),
    path('jobs/results/', job_results, name='job-results'),
    path('menus/<int:menu_id>/pages/', menu_pages, name='menu-pages'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/', dish_detail, name='dish-detail'),
    path('menus/<int:menu_id>/pages/<int:page_id>/dishes/', dish_list, name='dish-list'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/move/', move_dish, name='move-dish'),
    path('', index, name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
