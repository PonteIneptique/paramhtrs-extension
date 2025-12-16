<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:math="http://www.w3.org/2005/xpath-functions/math"
    exclude-result-prefixes="xs math"
    xpath-default-namespace="http://www.tei-c.org/ns/1.0"
    version="3.0">
    <xsl:output media-type="text/plain" method="text"/>
    <xsl:strip-space elements="*"/>
    <xsl:template match="ab">
        <xsl:apply-templates/>
    </xsl:template>
    <xsl:template match="choice"><xsl:apply-templates select="reg"/></xsl:template>
    <xsl:template match="orig"/>
    <xsl:template match="reg"><xsl:apply-templates/></xsl:template>        
    <xsl:template match="space"><xsl:text> </xsl:text></xsl:template>
    <xsl:template match="w"><xsl:apply-templates/></xsl:template>
    <xsl:template match="pc"><xsl:apply-templates/></xsl:template>
</xsl:stylesheet>