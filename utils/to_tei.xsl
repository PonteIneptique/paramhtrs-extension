<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:math="http://www.w3.org/2005/xpath-functions/math"
    exclude-result-prefixes="xs math"
    xmlns:local="http://localhost"
    xmlns="http://www.tei-c.org/ns/1.0"
    version="3.0">
    <!--
    Tokenize a string into <w>, <pc/>, and <sp/> nodes
    - words are split at apostrophes
    - punctuation: . : '
    - spaces preserved as <sp/>
  -->
    <xsl:function name="local:tokenize-w-pc-sp" as="node()*">
        <xsl:param name="text" as="xs:string"/>
        
        <xsl:analyze-string
            select="$text"
            regex="[^ .:'’]+|[.:'’]|\s">
            
            <xsl:matching-substring>
                <xsl:choose>
                    
                    <!-- space -->
                    <xsl:when test=". = ' '">
                        <space> </space>
                    </xsl:when>
                    
                    <!-- punctuation -->
                    <xsl:when test=". = '.' or . = ':' or . = &quot;'&quot; or . = '¶'">
                        <pc><xsl:value-of select="."/></pc>
                    </xsl:when>
                    
                    <!-- word -->
                    <xsl:otherwise>
                        <w><xsl:value-of select="."/></w>
                    </xsl:otherwise>
                    
                </xsl:choose>
            </xsl:matching-substring>
        </xsl:analyze-string>
    </xsl:function>
    <xsl:template match="text">
        <ab>
            <seg><xsl:apply-templates/></seg>
        </ab>
    </xsl:template>
    <xsl:template match="seg[not(./reg) and ./text() != ' ']">
        <xsl:choose>
            <xsl:when test="orig">
                <xsl:sequence select="local:tokenize-w-pc-sp(./orig)"/>
            </xsl:when>
            <xsl:otherwise>
                <xsl:sequence select="local:tokenize-w-pc-sp(.)"/>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>
    <xsl:template match="seg[not(./reg) and ./text() = ' ']">
        <space> </space>
    </xsl:template>
    <xsl:template match="seg[./reg/text() = ' ']">
        <reg><space> </space></reg>
    </xsl:template>
    <xsl:template match="seg">
        <choice>
            <orig><xsl:apply-templates select="orig"/></orig>
            <reg><xsl:apply-templates select="reg" /></reg>
        </choice>
    </xsl:template>
    <xsl:template match="orig"><xsl:apply-templates/></xsl:template>
    <xsl:template match="reg">
        <xsl:sequence select="local:tokenize-w-pc-sp(.)"/>
    </xsl:template>
</xsl:stylesheet>